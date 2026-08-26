from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
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

from break_even_image_tools import crop, read_rgb_image, resize_to_max_dim  # noqa: E402
from color_patch_metrics import patch_metric_rows, summarize_patch_metric_rows  # noqa: E402
from jxl_levels import DEFAULT_LEVELS, distance_for_level, require_level  # noqa: E402
from run_public_latitude_stress import build_transforms, metrics, write_ppm  # noqa: E402


DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs/rendered_ps16_jxl_matrix"
DEFAULT_RESULTS_DIR = ROOT / "results/rendered_ps16_jxl_matrix"
DEFAULT_CJXL = ROOT / "work/jxl-tools/bin/cjxl.exe"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"
HARD_TRANSFORM = "negative_density_hard_print"


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encode rendered PS16 TIFF masters as standalone JPEG XL, decode them, and measure codec loss."
    )
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--cjxl", type=Path)
    parser.add_argument("--djxl", type=Path)
    parser.add_argument("--effort", type=int, default=7)
    parser.add_argument("--limit", type=int, default=0, help="Limit number of PS16 renders for smoke tests.")
    parser.add_argument("--force", action="store_true")
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

    levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
    cjxl = find_tool("cjxl", DEFAULT_CJXL, args.cjxl)
    djxl = find_tool("djxl", DEFAULT_DJXL, args.djxl)
    renders = discover_ps16_renders(args.renders_root)
    if args.limit:
        renders = renders[: args.limit]

    rows: list[MatrixRow] = []
    pixel_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    for scan_set, set_id, source in renders:
        for level in levels:
            ppm, encoded, decoded = output_paths(args.output_root, source, level)
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
            if args.force or not usable_file(ppm):
                write_ppm(ppm, read_rgb_image(source))
            if args.force or not usable_file(encoded):
                ok, note = run_checked(encode_command(cjxl, ppm, encoded, level, args.effort))
                if not ok:
                    encoded.unlink(missing_ok=True)
                    row.status = "encode_failed"
                    row.notes = note
                    rows.append(row)
                    continue
            if args.force or not usable_file(decoded):
                decoded.unlink(missing_ok=True)
                ok, note = run_checked(decode_command(djxl, encoded, decoded))
                if not ok:
                    decoded.unlink(missing_ok=True)
                    row.status = "decode_failed"
                    row.notes = note
                    rows.append(row)
                    continue
            row.encoded_mib = mib(encoded)
            row.decoded_mib = mib(decoded)
            row.status = "encoded_decoded"
            if not args.no_metrics:
                try:
                    p_rows, patch = analyze_candidate(
                        scan_set,
                        set_id,
                        level,
                        source,
                        decoded,
                        args.results_dir,
                        patch_size=args.patch_size,
                        patch_color_space=args.patch_color_space,
                        crop_spec=args.crop,
                        max_analysis_dim=args.max_analysis_dim,
                    )
                except Exception as exc:
                    decoded.unlink(missing_ok=True)
                    row.status = "metrics_failed"
                    row.notes = str(exc)
                else:
                    pixel_rows.extend(p_rows)
                    patch_rows.extend(patch)
            rows.append(row)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.results_dir / "rendered_ps16_jxl_matrix.csv", rows)
    write_csv(args.results_dir / "pixel_metrics.csv", pixel_rows)
    write_csv(args.results_dir / "patch_metrics.csv", patch_rows)
    write_csv(args.results_dir / "patch_summary.csv", summarize_patch_metric_rows(patch_rows) if patch_rows else [])
    write_csv(
        args.results_dir / "break_even_patch_summary.csv",
        summarize_patch_metric_rows(patch_rows, ("scan_set", "set_id", "level", "transform"))
        if patch_rows
        else [],
    )
    write_csv(
        args.results_dir / "patch_luminance_summary.csv",
        summarize_patch_metric_rows(patch_rows, ("level", "transform", "luminance_bin"))
        if patch_rows
        else [],
    )
    write_csv(
        args.results_dir / "patch_chroma_summary.csv",
        summarize_patch_metric_rows(patch_rows, ("level", "transform", "chroma_bin"))
        if patch_rows
        else [],
    )
    (args.results_dir / "rendered_ps16_jxl_matrix.json").write_text(
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
    print(f"Wrote {len(rows)} rendered PS16 JXL row(s) to {relpath(args.results_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
