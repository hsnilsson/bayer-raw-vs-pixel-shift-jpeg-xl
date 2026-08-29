from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
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
DEFAULT_RENDERED_JXL_ROOT = ROOT / "outputs/rendered_ps16_jxl_matrix"
DEFAULT_OUTPUT_DIR = ROOT / "results/archival_break_even"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"


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


def find_tool(name: str, fallback: Path, explicit: Path | None = None) -> str:
    candidates = [str(explicit)] if explicit else []
    candidates.extend([name, str(fallback)])
    for candidate in candidates:
        found = shutil.which(candidate) if "\\" not in candidate and "/" not in candidate else None
        if found:
            return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    raise SystemExit(f"Could not find {name}; pass --{name} or place it at {fallback}")


def jxl_render_path(
    renders_root: Path,
    rendered_jxl_root: Path,
    scan_set: str,
    set_id: str,
    level: str,
    candidate_kind: str,
) -> Path:
    scan_slug = local_study.slugify(scan_set)
    if candidate_kind == "rendered_ps16_jxl":
        png = rendered_jxl_root / scan_slug / set_id / level / "ps16_candidate.png"
        if png.is_file():
            return png
        jxl = rendered_jxl_root / scan_slug / set_id / level / "ps16.jxl"
        if jxl.is_file():
            return jxl
        return rendered_jxl_root / scan_slug / set_id / level / "ps16_candidate.tif"
    if candidate_kind == "adc_dng_jxl":
        return renders_root / scan_slug / set_id / "adc_jxl_dng" / level / "ps16_candidate.tif"
    raise ValueError(f"unknown candidate kind: {candidate_kind}")


def collect_cases(
    input_root: Path,
    scan_roots: list[Path] | None,
    renders_root: Path,
    registered_root: Path,
    levels: list[str],
    rendered_jxl_root: Path,
    candidate_kind: str,
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
                cases.append(
                    (
                        scan_set,
                        set_id,
                        level,
                        reference,
                        raw61,
                        jxl_render_path(
                            renders_root,
                            rendered_jxl_root,
                            scan_set,
                            set_id,
                            level,
                            candidate_kind,
                        ),
                    )
                )
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


def read_jxl_candidate(path: Path, djxl: str) -> np.ndarray:
    if path.suffix.lower() != ".jxl":
        return read_rgb_image(path)
    with tempfile.TemporaryDirectory(prefix="structure-jxl-") as temp_dir:
        decoded = Path(temp_dir) / "candidate.ppm"
        subprocess.run(
            [djxl, str(path), str(decoded)],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return read_rgb_image(decoded)


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
    djxl: str | None = None,
    cached_jxl_detail: StructureDetailRow | None = None,
    cached_raw_detail: StructureDetailRow | None = None,
    prepared_reference: Any | None = None,
    prepared_raw61: Any | None = None,
    prepared_analysis_scale: float | None = None,
) -> tuple[StructureOutputRow, list[StructureDetailRow]]:
    scope = crop_spec or "full"
    if cached_raw_detail is not None and cached_jxl_detail is not None:
        raw_detail = replace(cached_raw_detail, level=level)
        risk = artifact_risk(cached_jxl_detail)
        verdict = structure_verdict(raw_detail.structure_loss, cached_jxl_detail.structure_loss, risk)
        return (
            StructureOutputRow(
                scan_set=scan_set,
                set_id=set_id,
                level=level,
                scope=scope,
                raw61_structure_loss=raw_detail.structure_loss,
                jxl_structure_loss=cached_jxl_detail.structure_loss,
                artifact_risk=risk,
                structure_verdict=verdict,
                notes=f"highpass_radius={highpass_radius}; crop={scope}; reused_raw61_detail=true; reused_jxl_detail=true",
            ),
            [raw_detail, cached_jxl_detail],
        )

    missing = [
        name
        for name, path in (
            ("PS16 render", reference_path),
            ("registered RAW61 render", raw61_path),
        )
        if not path.is_file()
    ]
    if cached_jxl_detail is None and not jxl_path.is_file():
        missing.append("JXL candidate render")
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

    if prepared_reference is None:
        reference = crop(read_rgb_image(reference_path), crop_spec)
    else:
        reference = prepared_reference
    if cached_raw_detail is None:
        raw61 = prepared_raw61 if prepared_raw61 is not None else crop(read_rgb_image(raw61_path), crop_spec)
    else:
        raw61 = None
    jxl = None
    if cached_jxl_detail is None:
        if jxl_path.suffix.lower() == ".jxl" and not djxl:
            raise ValueError("djxl is required when the JXL candidate path is a standalone .jxl file")
        jxl = crop(read_jxl_candidate(jxl_path, djxl or ""), crop_spec)
    if (raw61 is not None and reference.shape != raw61.shape) or (
        jxl is not None and reference.shape != jxl.shape
    ):
        raise ValueError(
            f"{scan_set}/{set_id}/{level}: structure input shapes differ after crop: "
            f"{reference.shape}, {raw61.shape}, {jxl.shape if jxl is not None else 'cached'}"
        )
    if prepared_reference is None:
        reference, analysis_scale = resize_to_max_dim(reference, max_analysis_dim)
    else:
        analysis_scale = prepared_analysis_scale or 1.0
    if raw61 is not None and prepared_raw61 is None:
        raw61, _ = resize_to_max_dim(raw61, max_analysis_dim)
    if cached_raw_detail is not None:
        raw_detail = replace(cached_raw_detail, level=level)
        raw_cache_note = "; reused_raw61_detail=true"
    else:
        assert raw61 is not None
        raw_detail = detail_row(scan_set, set_id, level, scope, "raw61_registered", reference, raw61, highpass_radius)
        raw_cache_note = ""
    if cached_jxl_detail is not None:
        jxl_detail = cached_jxl_detail
        cache_note = "; reused_jxl_detail=true"
    else:
        assert jxl is not None
        jxl, _ = resize_to_max_dim(jxl, max_analysis_dim)
        jxl_detail = detail_row(scan_set, set_id, level, scope, "ps16_jxl_candidate", reference, jxl, highpass_radius)
        cache_note = ""
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
            notes=f"highpass_radius={highpass_radius}; crop={scope}; analysis_scale={analysis_scale:.6g}{raw_cache_note}{cache_note}",
        ),
        [raw_detail, jxl_detail],
    )


def analyze_case_group(
    cases: list[tuple[str, str, str, Path, Path, Path]],
    crop_spec: str | None,
    highpass_radius: int,
    max_analysis_dim: int,
    djxl: str,
    reusable_jxl: dict[tuple[str, str, str, str], StructureDetailRow],
) -> tuple[list[StructureOutputRow], list[StructureDetailRow]]:
    rows: list[StructureOutputRow] = []
    details: list[StructureDetailRow] = []
    raw_detail_cache: dict[tuple[str, str, str], StructureDetailRow] = {}
    prepared_reference: Any | None = None
    prepared_raw61: Any | None = None
    prepared_analysis_scale: float | None = None
    for case in cases:
        scan_set, set_id, level = case[:3]
        scope = crop_spec or "full"
        cached_jxl = reusable_jxl.get((scan_set, set_id, level, scope))
        cached_raw = raw_detail_cache.get((scan_set, set_id, scope))
        if cached_jxl is None or cached_raw is None:
            reference_path = case[3]
            raw61_path = case[4]
            if prepared_reference is None and reference_path.is_file():
                prepared_reference = crop(read_rgb_image(reference_path), crop_spec)
                prepared_reference, prepared_analysis_scale = resize_to_max_dim(prepared_reference, max_analysis_dim)
            if cached_raw is None and prepared_raw61 is None and raw61_path.is_file():
                prepared_raw61 = crop(read_rgb_image(raw61_path), crop_spec)
                prepared_raw61, _ = resize_to_max_dim(prepared_raw61, max_analysis_dim)
        row, detail_rows = analyze_case(
            *case,
            crop_spec=crop_spec,
            highpass_radius=highpass_radius,
            max_analysis_dim=max_analysis_dim,
            djxl=djxl,
            cached_jxl_detail=cached_jxl,
            cached_raw_detail=cached_raw,
            prepared_reference=prepared_reference,
            prepared_raw61=prepared_raw61,
            prepared_analysis_scale=prepared_analysis_scale,
        )
        rows.append(row)
        details.extend(detail_rows)
        for detail in detail_rows:
            if detail.candidate_role == "raw61_registered":
                raw_detail_cache[(detail.scan_set, detail.set_id, detail.scope)] = detail
    return rows, details


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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [asdict(row) if hasattr(row, "__dataclass_fields__") else row for row in rows]


def merge_rows(path: Path, rows: list[Any], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    normalized_new = normalize_rows(rows)
    new_keys = {tuple(str(row.get(field, "")) for field in key_fields) for row in normalized_new}
    merged = [
        row
        for row in read_csv_rows(path)
        if tuple(str(row.get(field, "")) for field in key_fields) not in new_keys
    ]
    merged.extend(normalized_new)
    return merged


def write_json_output(path: Path, rows: list[Any], details: list[Any]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "rows": normalize_rows(rows),
                "details": normalize_rows(details),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_reusable_jxl_details(path: Path | None) -> dict[tuple[str, str, str, str], StructureDetailRow]:
    reusable: dict[tuple[str, str, str, str], StructureDetailRow] = {}
    if path is None or not path.is_file():
        return reusable
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("candidate_role") != "ps16_jxl_candidate":
                continue
            item = StructureDetailRow(
                scan_set=row.get("scan_set", ""),
                set_id=row.get("set_id", ""),
                level=row.get("level", ""),
                scope=row.get("scope", ""),
                candidate_role=row.get("candidate_role", ""),
                highpass_rmse=row.get("highpass_rmse", ""),
                highpass_reference_rms=row.get("highpass_reference_rms", ""),
                structure_loss=row.get("structure_loss", ""),
                detail_correlation=row.get("detail_correlation", ""),
                detail_energy_ratio=row.get("detail_energy_ratio", ""),
            )
            key = (item.scan_set, item.set_id, item.level, item.scope)
            if all(key):
                reusable[key] = item
    return reusable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure high-pass structure retention for RAW61 and PS16 JXL candidates."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--rendered-jxl-root", type=Path, default=DEFAULT_RENDERED_JXL_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--djxl", type=Path)
    parser.add_argument(
        "--candidate-kind",
        choices=["rendered_ps16_jxl", "adc_dng_jxl"],
        default="rendered_ps16_jxl",
    )
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel case groups. Keep low for full-resolution JXL decoding; 2-3 is usually safe.",
    )
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--raw61", type=Path)
    parser.add_argument("--jxl", type=Path)
    parser.add_argument(
        "--reuse-jxl-details-csv",
        type=Path,
        help="Reuse existing ps16_jxl_candidate detail rows and recompute only RAW61 structure.",
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge this run into existing output CSVs instead of replacing them.",
    )
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
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    djxl = find_tool("djxl", DEFAULT_DJXL, args.djxl)

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
        cases = collect_cases(
            args.input_root,
            args.scan_root,
            args.renders_root,
            args.registered_root,
            levels,
            args.rendered_jxl_root,
            args.candidate_kind,
        )

    rows: list[StructureOutputRow] = []
    details: list[StructureDetailRow] = []
    reusable_jxl = load_reusable_jxl_details(args.reuse_jxl_details_csv)
    if args.jobs == 1:
        rows, details = analyze_case_group(
            cases,
            crop_spec=args.crop,
            highpass_radius=args.highpass_radius,
            max_analysis_dim=args.max_analysis_dim,
            djxl=djxl,
            reusable_jxl=reusable_jxl,
        )
    else:
        grouped: dict[tuple[str, str], list[tuple[str, str, str, Path, Path, Path]]] = {}
        for case in cases:
            grouped.setdefault((case[0], case[1]), []).append(case)
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [
                executor.submit(
                    analyze_case_group,
                    group,
                    args.crop,
                    args.highpass_radius,
                    args.max_analysis_dim,
                    djxl,
                    reusable_jxl,
                )
                for group in grouped.values()
            ]
            for future in as_completed(futures):
                group_rows, group_details = future.result()
                rows.extend(group_rows)
                details.extend(group_details)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = args.output_dir / "structure_metrics.csv"
    details_path = args.output_dir / "structure_metrics_details.csv"
    if args.merge_existing:
        output_rows = merge_rows(rows_path, rows, ("scan_set", "set_id", "level", "scope"))
        output_details = merge_rows(
            details_path,
            details,
            ("scan_set", "set_id", "level", "scope", "candidate_role"),
        )
    else:
        output_rows = normalize_rows(rows)
        output_details = normalize_rows(details)
    write_csv(rows_path, output_rows)
    write_csv(details_path, output_details)
    write_json_output(args.output_dir / "structure_metrics.json", output_rows, output_details)
    print(f"Wrote {len(output_rows)} structure row(s) to {relpath(rows_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
