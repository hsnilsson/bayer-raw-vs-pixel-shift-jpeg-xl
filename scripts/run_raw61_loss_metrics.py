from __future__ import annotations

import argparse
import csv
import json
import math
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

from break_even_image_tools import clipping_fraction, crop, read_rgb_image, resize_to_max_dim  # noqa: E402
from color_patch_metrics import patch_metric_rows, summarize_patch_metric_rows  # noqa: E402
from run_public_latitude_stress import build_transforms, metrics  # noqa: E402
import run_local_scan_study as local_study  # noqa: E402


DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_REGISTERED_ROOT = ROOT / "outputs/registered_raw61_to_ps16"
DEFAULT_OUTPUT_DIR = ROOT / "results/archival_break_even"
HARD_TRANSFORM = "negative_density_hard_print"


@dataclass
class RawLossOutputRow:
    scan_set: str
    set_id: str
    raw61_color_delta_e00_p95_identity: float | None
    raw61_color_delta_e00_p95_stress: float | None
    raw61_channel_bias_max_stress: float | None
    raw61_clipping_delta_stress: float | None
    raw61_structure_loss: float | None
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


def rendered_reference_path(renders_root: Path, scan_set: str, set_id: str) -> Path:
    return renders_root / local_study.slugify(scan_set) / set_id / "ps16.tif"


def registered_raw61_path(registered_root: Path, scan_set: str, set_id: str) -> Path:
    return registered_root / local_study.slugify(scan_set) / set_id / "raw61_registered_to_ps16.tif"


def collect_pairs(
    input_root: Path,
    scan_roots: list[Path] | None,
    renders_root: Path,
    registered_root: Path,
) -> list[tuple[str, str, Path, Path]]:
    pairs: list[tuple[str, str, Path, Path]] = []
    for scan_root in discover_scan_roots(input_root, scan_roots):
        manifest = load_manifest(scan_root)
        if not manifest:
            continue
        scan_set = manifest.get("scan_root_name") or scan_root.name
        for capture in manifest.get("capture_sets", []):
            set_id = capture.get("set_id", "")
            if not capture.get("single_raw") or not capture.get("pixelshift16_dng"):
                continue
            pairs.append(
                (
                    scan_set,
                    set_id,
                    rendered_reference_path(renders_root, scan_set, set_id),
                    registered_raw61_path(registered_root, scan_set, set_id),
                )
            )
    return pairs


def float_or_none(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(result):
        return result
    return None


def channel_bias_max(summary: dict[str, Any] | None) -> float | None:
    if not summary:
        return None
    values = [
        abs(float(value))
        for key in ("mean_bias_r_16bit", "mean_bias_g_16bit", "mean_bias_b_16bit")
        for value in [summary.get(key)]
        if float_or_none(value) is not None
    ]
    return max(values) if values else None


def clipping_delta(reference_unit: Any, candidate_unit: Any) -> float:
    return abs(clipping_fraction(candidate_unit) - clipping_fraction(reference_unit))


def analyze_pair(
    scan_set: str,
    set_id: str,
    reference_path: Path,
    candidate_path: Path,
    output_dir: Path,
    patch_size: int,
    rgb_space: str,
    crop_spec: str | None,
    max_analysis_dim: int,
) -> RawLossOutputRow:
    if not reference_path.is_file():
        return RawLossOutputRow(scan_set, set_id, None, None, None, None, None, f"missing PS16 render: {relpath(reference_path)}")
    if not candidate_path.is_file():
        return RawLossOutputRow(scan_set, set_id, None, None, None, None, None, f"missing registered RAW61 render: {relpath(candidate_path)}")

    reference = crop(read_rgb_image(reference_path), crop_spec)
    candidate = crop(read_rgb_image(candidate_path), crop_spec)
    if reference.shape != candidate.shape:
        raise ValueError(f"{scan_set}/{set_id}: image shapes differ after crop: {reference.shape} != {candidate.shape}")
    reference, analysis_scale = resize_to_max_dim(reference, max_analysis_dim)
    candidate, _ = resize_to_max_dim(candidate, max_analysis_dim)

    pair_dir = output_dir / "raw61_loss_details" / local_study.slugify(scan_set) / set_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    transforms = {transform.name: transform for transform in build_transforms(reference)}
    wanted = ["identity", HARD_TRANSFORM]
    patch_rows: list[dict[str, Any]] = []
    pixel_rows: list[dict[str, Any]] = []
    clipping_by_transform: dict[str, float] = {}
    for name in wanted:
        transform = transforms[name]
        ref_t = transform.apply(reference)
        cand_t = transform.apply(candidate)
        metric = metrics(ref_t, cand_t)
        pixel_rows.append({"scan_set": scan_set, "set_id": set_id, "transform": name, **metric})
        clipping_by_transform[name] = clipping_delta(ref_t, cand_t)
        for patch_row in patch_metric_rows(ref_t, cand_t, patch_size=patch_size, rgb_space=rgb_space):
            patch_rows.append(
                {
                    "scan_set": scan_set,
                    "set_id": set_id,
                    "comparison": "raw61_to_ps16",
                    "transform": name,
                    **patch_row,
                }
            )

    summary_rows = summarize_patch_metric_rows(patch_rows, ("scan_set", "set_id", "transform"))
    summary_by_transform = {str(row["transform"]): row for row in summary_rows}
    write_csv(pair_dir / "raw61_patch_metrics.csv", patch_rows)
    write_csv(pair_dir / "raw61_patch_summary.csv", summary_rows)
    write_csv(pair_dir / "raw61_pixel_metrics.csv", pixel_rows)

    identity = summary_by_transform.get("identity")
    stress = summary_by_transform.get(HARD_TRANSFORM)
    return RawLossOutputRow(
        scan_set=scan_set,
        set_id=set_id,
        raw61_color_delta_e00_p95_identity=float_or_none(identity.get("p95_delta_e00")) if identity else None,
        raw61_color_delta_e00_p95_stress=float_or_none(stress.get("p95_delta_e00")) if stress else None,
        raw61_channel_bias_max_stress=channel_bias_max(stress),
        raw61_clipping_delta_stress=clipping_by_transform.get(HARD_TRANSFORM),
        raw61_structure_loss=None,
        notes=(
            f"crop={crop_spec or 'full'}; analysis_scale={analysis_scale:.6g}; "
            f"details={relpath(pair_dir)}"
        ),
    )


def write_csv(path: Path, rows: list[dict[str, Any]] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [asdict(row) if hasattr(row, "__dataclass_fields__") else row for row in rows]
    if not normalized:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(normalized[0].keys()))
        writer.writeheader()
        for row in normalized:
            writer.writerow(row)


def write_json_output(path: Path, rows: list[RawLossOutputRow]) -> None:
    path.write_text(
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
        description="Measure RAW61-vs-PS16 color/tone baseline loss for the archival break-even matrix."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--scan-set", default="manual")
    parser.add_argument("--set-id", default="manual")
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument(
        "--patch-color-space",
        default="prophoto-rgb",
        choices=["srgb", "display-p3", "adobe-rgb", "prophoto-rgb"],
    )
    parser.add_argument("--crop", help="Optional x,y,width,height crop in registered PS16 coordinates.")
    parser.add_argument(
        "--max-analysis-dim",
        type=int,
        default=2048,
        help="Downscale the longest side before analysis. Use 0 for full resolution or with native-detail crops.",
    )
    args = parser.parse_args()

    if args.patch_size <= 0:
        raise SystemExit("--patch-size must be positive")

    if args.reference or args.candidate:
        if not (args.reference and args.candidate):
            raise SystemExit("--reference and --candidate must be used together")
        pairs = [(args.scan_set, args.set_id, args.reference, args.candidate)]
    else:
        pairs = collect_pairs(args.input_root, args.scan_root, args.renders_root, args.registered_root)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        analyze_pair(
            scan_set,
            set_id,
            reference,
            candidate,
            args.output_dir,
            patch_size=args.patch_size,
            rgb_space=args.patch_color_space,
            crop_spec=args.crop,
            max_analysis_dim=args.max_analysis_dim,
        )
        for scan_set, set_id, reference, candidate in pairs
    ]
    write_csv(args.output_dir / "raw61_loss.csv", rows)
    write_json_output(args.output_dir / "raw61_loss.json", rows)
    print(f"Wrote {len(rows)} RAW61 loss row(s) to {relpath(args.output_dir / 'raw61_loss.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
