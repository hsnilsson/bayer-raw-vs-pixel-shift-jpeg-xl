from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from break_even_image_tools import crop, read_rgb_image, resize_to_max_dim  # noqa: E402
from color_patch_metrics import patch_metric_rows, summarize_patch_metric_rows  # noqa: E402
from incremental_cache import file_state, fingerprint, fresh, load_cache, make_entry, save_cache  # noqa: E402
from jxl_levels import DEFAULT_LEVELS, distance_for_level, require_level  # noqa: E402
from run_public_latitude_stress import build_transforms, metrics, write_ppm  # noqa: E402


DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs/rendered_ps16_jxl_matrix"
DEFAULT_RESULTS_DIR = ROOT / "results/rendered_ps16_jxl_matrix"
DEFAULT_CJXL = ROOT / "work/jxl-tools/bin/cjxl.exe"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"
HARD_TRANSFORM = "negative_density_hard_print"
CACHE_FILENAME = "artifact_cache.json"


@dataclass
class MatrixRow:
    scan_set: str
    set_id: str
    level: str
    source_tif: str
    encoded_jxl: str
    decoded_tif: str
    source_mib: float
    encoded_mib: float | None
    decoded_mib: float | None
    status: str
    notes: str


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def mib(path: Path | None) -> float | None:
    if path is None or not path.is_file():
        return None
    return path.stat().st_size / 1024 / 1024


def usable_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def cache_code_states() -> list[dict[str, Any] | None]:
    return [
        file_state(Path(__file__), ROOT),
        file_state(ROOT / "src/break_even_image_tools.py", ROOT),
        file_state(ROOT / "src/color_patch_metrics.py", ROOT),
        file_state(ROOT / "scripts/run_public_latitude_stress.py", ROOT),
    ]


def artifact_fingerprint(
    source: Path,
    level: str,
    cjxl: str,
    djxl: str,
    effort: int,
) -> str:
    return fingerprint(
        {
            "kind": "rendered_ps16_jxl_artifacts",
            "source": file_state(source, ROOT),
            "cjxl": file_state(Path(cjxl), ROOT),
            "djxl": file_state(Path(djxl), ROOT),
            "level": level,
            "distance": distance_for_level(level),
            "effort": effort,
            "code": cache_code_states(),
        }
    )


def metrics_fingerprint(
    source: Path,
    encoded: Path,
    decoded: Path,
    djxl: str,
    level: str,
    patch_size: int,
    patch_color_space: str,
    crop_spec: str | None,
    max_analysis_dim: int,
) -> str:
    return fingerprint(
        {
            "kind": "rendered_ps16_jxl_metrics",
            "source": file_state(source, ROOT),
            "encoded": file_state(encoded, ROOT),
            "decoded": file_state(decoded, ROOT),
            "djxl": file_state(Path(djxl), ROOT),
            "level": level,
            "patch_size": patch_size,
            "patch_color_space": patch_color_space,
            "crop": crop_spec,
            "max_analysis_dim": max_analysis_dim,
            "code": cache_code_states(),
        }
    )


def metric_cache_outputs(source: Path, encoded: Path, decoded: Path) -> dict[str, Path]:
    outputs = {"source": source, "encoded": encoded}
    if usable_file(decoded):
        outputs["decoded"] = decoded
    return outputs


def existing_metrics_are_current(
    source: Path,
    encoded: Path,
    key: tuple[str, str, str],
    pixel_keys: set[tuple[str, ...]],
    patch_keys: set[tuple[str, ...]],
) -> bool:
    return (
        existing_encoded_is_current(source, encoded)
        and key in pixel_keys
        and key in patch_keys
    )


def result_key(scan_set: str, set_id: str, level: str) -> tuple[str, str, str]:
    return scan_set, set_id, level


def result_key_set(rows: list[dict[str, str]], fields: tuple[str, ...]) -> set[tuple[str, ...]]:
    return {tuple(row.get(field, "") for field in fields) for row in rows}


def existing_artifacts_are_current(
    source: Path,
    encoded: Path,
    decoded: Path,
    matrix_row: dict[str, str] | None,
) -> bool:
    """Trust a pre-cache run once its recorded row and file timestamps agree."""
    if not matrix_row or matrix_row.get("status") != "encoded_decoded":
        return False
    if not usable_file(encoded) or not usable_file(decoded):
        return False
    return encoded.stat().st_mtime_ns >= source.stat().st_mtime_ns and decoded.stat().st_mtime_ns >= encoded.stat().st_mtime_ns


def existing_encoded_is_current(source: Path, encoded: Path) -> bool:
    return (
        usable_file(encoded)
        and encoded.stat().st_mtime_ns >= source.stat().st_mtime_ns
    )


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


def read_render_index(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def discover_ps16_renders(renders_root: Path) -> list[tuple[str, str, Path]]:
    rows = read_render_index(renders_root / "rawtherapee_render_index.csv")
    discovered: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for row in rows:
        if row.get("role") != "ps16" or row.get("status") not in {"rendered", "already_exists"}:
            continue
        path = (ROOT / row.get("output", "")).resolve()
        if path.is_file() and path not in seen:
            discovered.append((row.get("scan_set", ""), row.get("set_id", ""), path))
            seen.add(path)
    if discovered:
        return discovered
    for path in sorted(renders_root.rglob("ps16.tif")):
        set_id = path.parent.name
        scan_set = path.parent.parent.name
        discovered.append((scan_set, set_id, path.resolve()))
    return discovered


def output_paths(output_root: Path, source: Path, level: str) -> tuple[Path, Path, Path]:
    try:
        relative_parent = source.parent.relative_to(DEFAULT_RENDERS_ROOT.resolve())
    except ValueError:
        relative_parent = Path(source.parent.name)
    source_folder = output_root / relative_parent
    level_folder = source_folder / level
    return source_folder / "ps16_reference.ppm", level_folder / "ps16.jxl", level_folder / "ps16_candidate.png"


def encode_command(cjxl: str, source: Path, encoded: Path, level: str, effort: int) -> list[str]:
    cmd = [cjxl, str(source), str(encoded), "-e", str(effort)]
    distance = distance_for_level(level)
    if distance is None:
        cmd.append("-d")
        cmd.append("0")
    else:
        cmd.extend(["-d", distance])
    return cmd


def decode_command(djxl: str, encoded: Path, decoded: Path) -> list[str]:
    return [djxl, str(encoded), str(decoded)]


def run_checked(cmd: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return True, ""
    lines = (result.stdout + result.stderr).strip().splitlines()
    return False, lines[-1] if lines else f"exit code {result.returncode}"


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


def normalize_rows(rows: list[dict[str, Any]] | list[Any]) -> list[dict[str, Any]]:
    return [asdict(row) if hasattr(row, "__dataclass_fields__") else row for row in rows]


def merge_rows(
    existing_path: Path,
    new_rows: list[dict[str, Any]] | list[Any],
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    normalized_new = normalize_rows(new_rows)
    new_keys = {tuple(str(row.get(field, "")) for field in key_fields) for row in normalized_new}
    merged = [
        row
        for row in read_csv_rows(existing_path)
        if tuple(str(row.get(field, "")) for field in key_fields) not in new_keys
    ]
    merged.extend(normalized_new)
    return merged


def analyze_candidate(
    scan_set: str,
    set_id: str,
    level: str,
    source: Path,
    decoded: Path,
    results_dir: Path,
    patch_size: int,
    patch_color_space: str,
    crop_spec: str | None,
    max_analysis_dim: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference = crop(read_rgb_image(source), crop_spec)
    candidate = crop(read_rgb_image(decoded), crop_spec)
    if reference.shape != candidate.shape:
        raise ValueError(f"{scan_set}/{set_id}/{level}: decoded shape differs from source")
    reference, analysis_scale = resize_to_max_dim(reference, max_analysis_dim)
    candidate, _ = resize_to_max_dim(candidate, max_analysis_dim)
    transforms = build_transforms(reference)
    pixel_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    for transform in transforms:
        ref_t = transform.apply(reference)
        cand_t = transform.apply(candidate)
        pixel_rows.append(
            {
                "scan_set": scan_set,
                "set_id": set_id,
                "level": level,
                "transform": transform.name,
                "analysis_scale": analysis_scale,
                **metrics(ref_t, cand_t),
            }
        )
        for row in patch_metric_rows(
            ref_t,
            cand_t,
            patch_size=patch_size,
            rgb_space=patch_color_space,
        ):
            patch_rows.append(
                {
                    "scan_set": scan_set,
                    "set_id": set_id,
                    "level": level,
                    "transform": transform.name,
                    "analysis_scale": analysis_scale,
                    **row,
                }
            )
    return pixel_rows, patch_rows


def process_render_level(
    scan_set: str,
    set_id: str,
    source: Path,
    level: str,
    output_root: Path,
    results_dir: Path,
    cjxl: str,
    djxl: str,
    effort: int,
    force: bool,
    discard_intermediates: bool,
    no_metrics: bool,
    patch_size: int,
    patch_color_space: str,
    crop_spec: str | None,
    max_analysis_dim: int,
) -> tuple[MatrixRow, list[dict[str, Any]], list[dict[str, Any]]]:
    ppm, encoded, decoded = output_paths(output_root, source, level)
    encoded.parent.mkdir(parents=True, exist_ok=True)
    row = MatrixRow(
        scan_set=scan_set,
        set_id=set_id,
        level=level,
        source_tif=relpath(source),
        encoded_jxl=relpath(encoded),
        decoded_tif=relpath(decoded),
        source_mib=mib(source) or 0.0,
        encoded_mib=mib(encoded),
        decoded_mib=mib(decoded),
        status="pending",
        notes="",
    )
    if force or not usable_file(encoded):
        ok, note = run_checked(encode_command(cjxl, ppm, encoded, level, effort))
        if not ok:
            encoded.unlink(missing_ok=True)
            row.status = "encode_failed"
            row.notes = note
            return row, [], []
    if force or not usable_file(decoded):
        decoded.unlink(missing_ok=True)
        ok, note = run_checked(decode_command(djxl, encoded, decoded))
        if not ok:
            decoded.unlink(missing_ok=True)
            row.status = "decode_failed"
            row.notes = note
            return row, [], []
    row.encoded_mib = mib(encoded)
    row.decoded_mib = mib(decoded)
    row.status = "encoded_decoded"
    pixel_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    if not no_metrics:
        try:
            pixel_rows, patch_rows = analyze_candidate(
                scan_set,
                set_id,
                level,
                source,
                decoded,
                results_dir,
                patch_size=patch_size,
                patch_color_space=patch_color_space,
                crop_spec=crop_spec,
                max_analysis_dim=max_analysis_dim,
            )
        except Exception as exc:
            decoded.unlink(missing_ok=True)
            row.status = "metrics_failed"
            row.notes = str(exc)
            return row, [], []
    if discard_intermediates:
        decoded.unlink(missing_ok=True)
    return row, pixel_rows, patch_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encode rendered PS16 TIFF masters as standalone JPEG XL, decode them, and measure codec loss."
    )
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--scan-set", action="append", default=None, help="Only process these scan_set values.")
    parser.add_argument("--set-id", action="append", default=None, help="Only process these set_id values.")
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--cjxl", type=Path)
    parser.add_argument("--djxl", type=Path)
    parser.add_argument("--effort", type=int, default=7)
    parser.add_argument("--limit", type=int, default=0, help="Limit number of PS16 renders for smoke tests.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel image jobs. Keep low for full-resolution runs; 2-3 is usually safer than maxing the CPU.",
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge this run into existing result CSVs instead of replacing them.",
    )
    parser.add_argument(
        "--no-incremental",
        dest="incremental",
        action="store_false",
        help="Revisit every selected row instead of reusing the artifact cache.",
    )
    parser.set_defaults(incremental=True)
    parser.add_argument(
        "--discard-intermediates",
        action="store_true",
        help="Delete decoded PNG and reference PPM intermediates after metrics are written.",
    )
    parser.add_argument("--no-metrics", action="store_true")
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument(
        "--patch-color-space",
        default="prophoto-rgb",
        choices=["srgb", "display-p3", "adobe-rgb", "prophoto-rgb"],
    )
    parser.add_argument("--crop", help="Optional x,y,width,height crop in PS16 coordinates.")
    parser.add_argument("--max-analysis-dim", type=int, default=2048)
    args = parser.parse_args()

    if args.patch_size <= 0:
        raise SystemExit("--patch-size must be positive")
    if args.effort < 1 or args.effort > 9:
        raise SystemExit("--effort must be between 1 and 9")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")

    levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
    cjxl = find_tool("cjxl", DEFAULT_CJXL, args.cjxl)
    djxl = find_tool("djxl", DEFAULT_DJXL, args.djxl)
    renders = discover_ps16_renders(args.renders_root)
    if args.scan_set:
        allowed_scan_sets = set(args.scan_set)
        renders = [item for item in renders if item[0] in allowed_scan_sets]
    if args.set_id:
        allowed_set_ids = set(args.set_id)
        renders = [item for item in renders if item[1] in allowed_set_ids]
    if args.limit:
        renders = renders[: args.limit]

    cache_path = args.results_dir / CACHE_FILENAME
    cache = load_cache(cache_path)
    cache_entries = cache.setdefault("entries", {})
    existing_matrix_rows = read_csv_rows(args.results_dir / "rendered_ps16_jxl_matrix.csv")
    existing_pixel_rows = read_csv_rows(args.results_dir / "pixel_metrics.csv")
    existing_patch_rows = read_csv_rows(args.results_dir / "patch_metrics.csv")
    existing_matrix_by_key = {
        result_key(row.get("scan_set", ""), row.get("set_id", ""), row.get("level", "")): row
        for row in existing_matrix_rows
    }
    existing_pixel_keys = result_key_set(existing_pixel_rows, ("scan_set", "set_id", "level"))
    existing_patch_keys = result_key_set(existing_patch_rows, ("scan_set", "set_id", "level"))

    source_ppms: dict[Path, Path] = {}
    jobs = []
    cached_rows: list[MatrixRow] = []
    skipped_cached = 0
    for scan_set, set_id, source in renders:
        for level in levels:
            ppm, encoded, decoded = output_paths(args.output_root, source, level)
            key = "|".join(result_key(scan_set, set_id, level))
            entry = cache_entries.get(key) if isinstance(cache_entries.get(key), dict) else {}
            artifact_entry = entry.get("artifact") if isinstance(entry.get("artifact"), dict) else None
            artifact_fp = artifact_fingerprint(source, level, cjxl, djxl, args.effort)
            artifact_outputs = {"encoded": encoded, "decoded": decoded}
            artifact_fresh = fresh(artifact_entry, artifact_fp, artifact_outputs, ROOT)
            encoded_fresh = fresh(artifact_entry, artifact_fp, {"encoded": encoded}, ROOT)
            if not encoded_fresh:
                encoded_fresh = existing_encoded_is_current(source, encoded)
            if not artifact_fresh and existing_artifacts_are_current(
                source, encoded, decoded, existing_matrix_by_key.get(result_key(scan_set, set_id, level))
            ):
                artifact_fresh = True
                artifact_entry = make_entry(artifact_fp, artifact_outputs, ROOT)

            metric_fp = metrics_fingerprint(
                source,
                encoded,
                decoded,
                djxl,
                level,
                args.patch_size,
                args.patch_color_space,
                args.crop,
                args.max_analysis_dim,
            )
            metric_entry = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else None
            metric_outputs = metric_cache_outputs(source, encoded, decoded)
            metric_fresh = (
                artifact_fresh
                and result_key(scan_set, set_id, level) in existing_pixel_keys
                and result_key(scan_set, set_id, level) in existing_patch_keys
                and fresh(metric_entry, metric_fp, metric_outputs, ROOT)
            )
            if not metric_fresh and args.incremental and existing_metrics_are_current(
                source,
                encoded,
                result_key(scan_set, set_id, level),
                existing_pixel_keys,
                existing_patch_keys,
            ):
                metric_fresh = True
                artifact_entry = artifact_entry or make_entry(artifact_fp, {"encoded": encoded}, ROOT)
                metric_entry = make_entry(metric_fp, metric_outputs, ROOT)
            can_skip = args.incremental and not args.force and (
                (args.no_metrics and artifact_fresh) or metric_fresh
            )
            if can_skip:
                cache_entries[key] = {
                    "artifact": artifact_entry or make_entry(artifact_fp, artifact_outputs, ROOT),
                    "metrics": metric_entry or make_entry(metric_fp, metric_outputs, ROOT),
                }
                existing = existing_matrix_by_key.get(result_key(scan_set, set_id, level))
                if existing and existing.get("status") != "encoded_decoded":
                    cached_rows.append(
                        MatrixRow(
                            scan_set=scan_set,
                            set_id=set_id,
                            level=level,
                            source_tif=relpath(source),
                            encoded_jxl=relpath(encoded),
                            decoded_tif=existing.get("decoded_tif", relpath(decoded)),
                            source_mib=mib(source) or 0.0,
                            encoded_mib=mib(encoded),
                            decoded_mib=float(existing.get("decoded_mib") or 0.0) or None,
                            status="encoded_decoded",
                            notes="reused existing encoded artifact and stored metrics",
                        )
                    )
                skipped_cached += 1
                continue

            encode_required = args.force or not encoded_fresh
            if encode_required:
                source_ppms[ppm] = source
            jobs.append(
                (
                    scan_set,
                    set_id,
                    source,
                    level,
                    args.output_root,
                    args.results_dir,
                    cjxl,
                    djxl,
                    args.effort,
                    encode_required,
                    args.discard_intermediates,
                    args.no_metrics,
                    args.patch_size,
                    args.patch_color_space,
                    args.crop,
                    args.max_analysis_dim,
                )
            )

    print(f"Planned {len(jobs)} row(s); reused {skipped_cached} cached row(s).")
    for ppm, source in source_ppms.items():
        if args.force or not usable_file(ppm) or ppm.stat().st_mtime_ns < source.stat().st_mtime_ns:
            ppm.parent.mkdir(parents=True, exist_ok=True)
            write_ppm(ppm, read_rgb_image(source))

    rows: list[MatrixRow] = list(cached_rows)
    pixel_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    if args.jobs == 1:
        for job in jobs:
            row, p_rows, patch = process_render_level(*job)
            rows.append(row)
            pixel_rows.extend(p_rows)
            patch_rows.extend(patch)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(process_render_level, *job) for job in jobs]
            for future in as_completed(futures):
                row, p_rows, patch = future.result()
                rows.append(row)
                pixel_rows.extend(p_rows)
                patch_rows.extend(patch)

    for row in rows:
        if row.status != "encoded_decoded":
            continue
        _ppm, encoded, decoded = output_paths(
            args.output_root,
            Path(ROOT / row.source_tif),
            row.level,
        )
        artifact_fp = artifact_fingerprint(Path(ROOT / row.source_tif), row.level, cjxl, djxl, args.effort)
        key = "|".join(result_key(row.scan_set, row.set_id, row.level))
        cache_entry = {"artifact": make_entry(artifact_fp, {"encoded": encoded, "decoded": decoded}, ROOT)}
        if not args.no_metrics and any(
            item.get("scan_set") == row.scan_set
            and item.get("set_id") == row.set_id
            and item.get("level") == row.level
            for item in pixel_rows
        ):
            metric_fp = metrics_fingerprint(
                Path(ROOT / row.source_tif),
                encoded,
                decoded,
                djxl,
                row.level,
                args.patch_size,
                args.patch_color_space,
                args.crop,
                args.max_analysis_dim,
            )
            cache_entry["metrics"] = make_entry(
                metric_fp,
                metric_cache_outputs(Path(ROOT / row.source_tif), encoded, decoded),
                ROOT,
            )
        cache_entries[key] = cache_entry

    if args.discard_intermediates:
        for ppm in source_ppms:
            ppm.unlink(missing_ok=True)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    if args.merge_existing or args.incremental:
        matrix_rows = merge_rows(
            args.results_dir / "rendered_ps16_jxl_matrix.csv",
            rows,
            ("scan_set", "set_id", "level"),
        )
        pixel_output_rows = merge_rows(
            args.results_dir / "pixel_metrics.csv",
            pixel_rows,
            ("scan_set", "set_id", "level", "transform"),
        )
        patch_output_rows = merge_rows(
            args.results_dir / "patch_metrics.csv",
            patch_rows,
            ("scan_set", "set_id", "level", "transform", "patch_id"),
        )
    else:
        matrix_rows = normalize_rows(rows)
        pixel_output_rows = pixel_rows
        patch_output_rows = patch_rows
    write_csv(args.results_dir / "rendered_ps16_jxl_matrix.csv", matrix_rows)
    write_csv(args.results_dir / "pixel_metrics.csv", pixel_output_rows)
    write_csv(args.results_dir / "patch_metrics.csv", patch_output_rows)
    write_csv(args.results_dir / "patch_summary.csv", summarize_patch_metric_rows(patch_output_rows) if patch_output_rows else [])
    write_csv(
        args.results_dir / "break_even_patch_summary.csv",
        summarize_patch_metric_rows(patch_output_rows, ("scan_set", "set_id", "level", "transform"))
        if patch_output_rows
        else [],
    )
    write_csv(
        args.results_dir / "patch_luminance_summary.csv",
        summarize_patch_metric_rows(patch_output_rows, ("level", "transform", "luminance_bin"))
        if patch_output_rows
        else [],
    )
    write_csv(
        args.results_dir / "patch_chroma_summary.csv",
        summarize_patch_metric_rows(patch_output_rows, ("level", "transform", "chroma_bin"))
        if patch_output_rows
        else [],
    )
    (args.results_dir / "rendered_ps16_jxl_matrix.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "rows": matrix_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    save_cache(cache_path, cache)
    print(f"Wrote {len(matrix_rows)} rendered PS16 JXL row(s) to {relpath(args.results_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
