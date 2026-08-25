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

from break_even_image_tools import (
    crop,
    finite_float,
    read_rgb_image,
    resize_to_max_dim,
    structure_metrics,
)  # noqa: E402
from jxl_levels import DEFAULT_LEVELS, require_level  # noqa: E402
import run_local_scan_study as local_study  # noqa: E402


DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_REGISTERED_ROOT = ROOT / "outputs/registered_raw61_to_ps16"
DEFAULT_OUTPUT_DIR = ROOT / "results/archival_break_even"


@dataclass
class StructureOutputRow:
    scan_set: str
    set_id: str
    level: str
    scope: str
    raw61_structure_loss: float | str | None
    jxl_structure_loss: float | str | None
    artifact_risk: str
    structure_verdict: str
    notes: str


@dataclass
class StructureDetailRow:
    scan_set: str
    set_id: str
    level: str
    scope: str
    candidate_role: str
    highpass_rmse: float | str
    highpass_reference_rms: float | str
    structure_loss: float | str
    detail_correlation: float | str
    detail_energy_ratio: float | str


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


def ps16_render_path(renders_root: Path, scan_set: str, set_id: str) -> Path:
    return renders_root / local_study.slugify(scan_set) / set_id / "ps16.tif"


def raw61_registered_path(registered_root: Path, scan_set: str, set_id: str) -> Path:
    return registered_root / local_study.slugify(scan_set) / set_id / "raw61_registered_to_ps16.tif"


def jxl_render_path(renders_root: Path, scan_set: str, set_id: str, level: str) -> Path:
    return renders_root / local_study.slugify(scan_set) / set_id / "adc_jxl_dng" / level / "ps16_candidate.tif"


def collect_cases(
    input_root: Path,
    scan_roots: list[Path] | None,
    renders_root: Path,
    registered_root: Path,
    levels: list[str],
) -> list[tuple[str, str, str, Path, Path, Path]]:
    cases: list[tuple[str, str, str, Path, Path, Path]] = []
    for scan_root in discover_scan_roots(input_root, scan_roots):
        manifest = load_manifest(scan_root)
        if not manifest:
            continue
        scan_set = manifest.get("scan_root_name") or scan_root.name
        for capture in manifest.get("capture_sets", []):
            set_id = capture.get("set_id", "")
            if not capture.get("single_raw") or not capture.get("pixelshift16_dng"):
                continue
            reference = ps16_render_path(renders_root, scan_set, set_id)
            raw61 = raw61_registered_path(registered_root, scan_set, set_id)
            for level in levels:
                cases.append((scan_set, set_id, level, reference, raw61, jxl_render_path(renders_root, scan_set, set_id, level)))
    return cases


def is_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def structure_verdict(raw_loss: object, jxl_loss: object, artifact_risk: str) -> str:
    if not is_number(raw_loss):
        return "blocked_missing_raw61_structure"
    if not is_number(jxl_loss):
        return "blocked_missing_jxl_structure"
    if artifact_risk == "high":
        return "blocked_artifact_risk"
    raw = float(raw_loss)
    jxl = float(jxl_loss)
    if jxl < raw * 0.8:
        return "ps16_jxl_likely_wins"
    if jxl <= raw * 1.1:
        return "uncertain"
    return "raw61_likely_wins"


def artifact_risk(jxl_detail: StructureDetailRow) -> str:
    if is_number(jxl_detail.detail_correlation) and float(jxl_detail.detail_correlation) < 0.70:
        return "high"
    if is_number(jxl_detail.detail_energy_ratio):
        ratio = float(jxl_detail.detail_energy_ratio)
        if ratio < 0.50 or ratio > 1.80:
            return "high"
    if is_number(jxl_detail.detail_correlation) and float(jxl_detail.detail_correlation) < 0.85:
        return "medium"
    if is_number(jxl_detail.detail_energy_ratio):
        ratio = float(jxl_detail.detail_energy_ratio)
        if ratio < 0.70 or ratio > 1.35:
            return "medium"
    return "low"


def detail_row(
    scan_set: str,
    set_id: str,
    level: str,
    scope: str,
    candidate_role: str,
    reference: Any,
    candidate: Any,
    highpass_radius: int,
) -> StructureDetailRow:
    metrics = structure_metrics(reference, candidate, radius=highpass_radius)
    return StructureDetailRow(
        scan_set=scan_set,
        set_id=set_id,
        level=level,
        scope=scope,
        candidate_role=candidate_role,
        highpass_rmse=finite_float(metrics.highpass_rmse),
        highpass_reference_rms=finite_float(metrics.highpass_reference_rms),
        structure_loss=finite_float(metrics.structure_loss),
        detail_correlation=finite_float(metrics.detail_correlation),
        detail_energy_ratio=finite_float(metrics.detail_energy_ratio),
    )


def analyze_case(
    scan_set: str,
    set_id: str,
    level: str,
    reference_path: Path,
    raw61_path: Path,
    jxl_path: Path,
    crop_spec: str | None,
    highpass_radius: int,
    max_analysis_dim: int,
) -> tuple[StructureOutputRow, list[StructureDetailRow]]:
    missing = [
        name
        for name, path in (
            ("PS16 render", reference_path),
            ("registered RAW61 render", raw61_path),
            ("JXL candidate render", jxl_path),
        )
        if not path.is_file()
    ]
    if missing:
        return (
            StructureOutputRow(
                scan_set=scan_set,
                set_id=set_id,
                level=level,
                scope=crop_spec or "full",
                raw61_structure_loss=None,
                jxl_structure_loss=None,
                artifact_risk="unknown",
                structure_verdict="blocked_missing_structure_inputs",
                notes="missing " + ", ".join(missing),
            ),
            [],
        )

    reference = crop(read_rgb_image(reference_path), crop_spec)
    raw61 = crop(read_rgb_image(raw61_path), crop_spec)
    jxl = crop(read_rgb_image(jxl_path), crop_spec)
    if reference.shape != raw61.shape or reference.shape != jxl.shape:
        raise ValueError(
            f"{scan_set}/{set_id}/{level}: structure input shapes differ after crop: "
            f"{reference.shape}, {raw61.shape}, {jxl.shape}"
        )
    reference, analysis_scale = resize_to_max_dim(reference, max_analysis_dim)
    raw61, _ = resize_to_max_dim(raw61, max_analysis_dim)
    jxl, _ = resize_to_max_dim(jxl, max_analysis_dim)
    scope = crop_spec or "full"
    raw_detail = detail_row(scan_set, set_id, level, scope, "raw61_registered", reference, raw61, highpass_radius)
    jxl_detail = detail_row(scan_set, set_id, level, scope, "ps16_jxl_candidate", reference, jxl, highpass_radius)
    risk = artifact_risk(jxl_detail)
    verdict = structure_verdict(raw_detail.structure_loss, jxl_detail.structure_loss, risk)
    return (
        StructureOutputRow(
            scan_set=scan_set,
            set_id=set_id,
            level=level,
            scope=scope,
            raw61_structure_loss=raw_detail.structure_loss,
            jxl_structure_loss=jxl_detail.structure_loss,
            artifact_risk=risk,
            structure_verdict=verdict,
            notes=f"highpass_radius={highpass_radius}; crop={scope}; analysis_scale={analysis_scale:.6g}",
        ),
        [raw_detail, jxl_detail],
    )


def write_csv(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [asdict(row) if hasattr(row, "__dataclass_fields__") else row for row in rows]
    if not normalized:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(normalized[0].keys()))
        writer.writeheader()
        for row in normalized:
            writer.writerow(row)


def write_json_output(path: Path, rows: list[StructureOutputRow], details: list[StructureDetailRow]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "rows": [asdict(row) for row in rows],
                "details": [asdict(row) for row in details],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure high-pass structure retention for RAW61 and PS16 JXL candidates."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--raw61", type=Path)
    parser.add_argument("--jxl", type=Path)
    parser.add_argument("--scan-set", default="manual")
    parser.add_argument("--set-id", default="manual")
    parser.add_argument("--manual-level", default="d005")
    parser.add_argument("--crop", help="Optional x,y,width,height crop in registered PS16 coordinates.")
    parser.add_argument("--highpass-radius", type=int, default=2)
    parser.add_argument(
        "--max-analysis-dim",
        type=int,
        default=2048,
        help="Downscale the longest side before analysis. Use 0 for full resolution or with native-detail crops.",
    )
    args = parser.parse_args()

    if args.highpass_radius <= 0:
        raise SystemExit("--highpass-radius must be positive")

    if args.reference or args.raw61 or args.jxl:
        if not (args.reference and args.raw61 and args.jxl):
            raise SystemExit("--reference, --raw61, and --jxl must be used together")
        cases = [
            (
                args.scan_set,
                args.set_id,
                require_level(args.manual_level),
                args.reference,
                args.raw61,
                args.jxl,
            )
        ]
    else:
        levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
        cases = collect_cases(args.input_root, args.scan_root, args.renders_root, args.registered_root, levels)

    rows: list[StructureOutputRow] = []
    details: list[StructureDetailRow] = []
    for case in cases:
        row, detail_rows = analyze_case(
            *case,
            crop_spec=args.crop,
            highpass_radius=args.highpass_radius,
            max_analysis_dim=args.max_analysis_dim,
        )
        rows.append(row)
        details.extend(detail_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "structure_metrics.csv", rows)
    write_csv(args.output_dir / "structure_metrics_details.csv", details)
    write_json_output(args.output_dir / "structure_metrics.json", rows, details)
    print(f"Wrote {len(rows)} structure row(s) to {relpath(args.output_dir / 'structure_metrics.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
