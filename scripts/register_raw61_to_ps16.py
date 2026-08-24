from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from break_even_image_tools import (  # noqa: E402
    read_rgb_image,
    register_candidate_to_reference,
    write_json,
    write_rgb_tiff,
)
import run_local_scan_study as local_study  # noqa: E402


DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs/registered_raw61_to_ps16"


@dataclass
class RegistrationIndexRow:
    scan_set: str
    set_id: str
    reference: str
    candidate: str
    output: str
    scale_x: float | None
    scale_y: float | None
    shift_x_px: float | None
    shift_y_px: float | None
    overlap_fraction: float | None
    phase_peak_to_median: float | None
    status: str
    notes: str


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_manifest(scan_root: Path) -> dict[str, Any] | None:
    path = scan_root / "scan_manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def discover_scan_roots(input_root: Path, explicit_roots: list[Path] | None) -> list[Path]:
    if explicit_roots:
        return [path.resolve() for path in explicit_roots]
    if not input_root.is_dir():
        return []
    return [
        path.resolve()
        for path in sorted(input_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and not path.name.startswith("_")
    ]


def rendered_pair_paths(renders_root: Path, scan_set: str, set_id: str) -> tuple[Path, Path]:
    folder = renders_root / local_study.slugify(scan_set) / set_id
    return folder / "ps16.tif", folder / "raw61.tif"


def registered_output_path(output_root: Path, scan_set: str, set_id: str) -> Path:
    return output_root / local_study.slugify(scan_set) / set_id / "raw61_registered_to_ps16.tif"


def collect_pairs(
    input_root: Path,
    scan_roots: list[Path] | None,
    renders_root: Path,
    output_root: Path,
) -> list[tuple[str, str, Path, Path, Path]]:
    pairs: list[tuple[str, str, Path, Path, Path]] = []
    for scan_root in discover_scan_roots(input_root, scan_roots):
        manifest = load_manifest(scan_root)
        if not manifest:
            continue
        scan_set = manifest.get("scan_root_name") or scan_root.name
        for capture in manifest.get("capture_sets", []):
            set_id = capture.get("set_id", "")
            if not capture.get("single_raw") or not capture.get("pixelshift16_dng"):
                continue
            reference, candidate = rendered_pair_paths(renders_root, scan_set, set_id)
            output = registered_output_path(output_root, scan_set, set_id)
            pairs.append((scan_set, set_id, reference, candidate, output))
    return pairs


def register_one(
    scan_set: str,
    set_id: str,
    reference_path: Path,
    candidate_path: Path,
    output_path: Path,
    max_preview_dim: int,
    force: bool,
) -> RegistrationIndexRow:
    row = RegistrationIndexRow(
        scan_set=scan_set,
        set_id=set_id,
        reference=relpath(reference_path),
        candidate=relpath(candidate_path),
        output=relpath(output_path),
        scale_x=None,
        scale_y=None,
        shift_x_px=None,
        shift_y_px=None,
        overlap_fraction=None,
        phase_peak_to_median=None,
        status="pending",
        notes="",
    )
    if not reference_path.is_file():
        row.status = "missing_reference"
        row.notes = f"missing reference render: {relpath(reference_path)}"
        return row
    if not candidate_path.is_file():
        row.status = "missing_candidate"
        row.notes = f"missing RAW61 render: {relpath(candidate_path)}"
        return row
    metadata_path = output_path.with_suffix(".registration.json")
    if output_path.is_file() and metadata_path.is_file() and not force:
        row.status = "already_exists"
        return row

    reference = read_rgb_image(reference_path)
    candidate = read_rgb_image(candidate_path)
    registered, result = register_candidate_to_reference(
        reference, candidate, max_preview_dim=max_preview_dim
    )
    write_rgb_tiff(output_path, registered)
    write_json(metadata_path, result)
    row.scale_x = result.scale_x
    row.scale_y = result.scale_y
    row.shift_x_px = result.shift_x_px
    row.shift_y_px = result.shift_y_px
    row.overlap_fraction = result.overlap_fraction
    row.phase_peak_to_median = result.phase_peak_to_median
    row.status = "registered"
    if result.overlap_fraction < 0.95:
        row.notes = "review: low overlap after registration"
    elif result.phase_peak_to_median < 20.0:
        row.notes = "review: weak phase-correlation peak"
    return row


def write_index(rows: list[RegistrationIndexRow], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    if rows:
        with (output_root / "registration_index.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
    (output_root / "registration_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "rows": [asdict(row) for row in rows],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a 61 MP raw render to the corresponding PS16 render."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scan-set", default="manual")
    parser.add_argument("--set-id", default="manual")
    parser.add_argument("--max-preview-dim", type=int, default=2048)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.max_preview_dim <= 0:
        raise SystemExit("--max-preview-dim must be positive")

    if args.reference or args.candidate or args.output:
        if not (args.reference and args.candidate and args.output):
            raise SystemExit("--reference, --candidate, and --output must be used together")
        pairs = [(args.scan_set, args.set_id, args.reference, args.candidate, args.output)]
    else:
        pairs = collect_pairs(args.input_root, args.scan_root, args.renders_root, args.output_root)

    rows = [
        register_one(
            scan_set,
            set_id,
            reference,
            candidate,
            output,
            max_preview_dim=args.max_preview_dim,
            force=args.force,
        )
        for scan_set, set_id, reference, candidate, output in pairs
    ]
    write_index(rows, args.output_root)
    print(f"Wrote {len(rows)} registration row(s) to {relpath(args.output_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
