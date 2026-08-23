from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jxl_levels import DEFAULT_LEVELS, require_level


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_VERIFICATION_ROOT = ROOT / "results/dng_jxl_verification"
DEFAULT_INDEX_DIR = ROOT / "results/local_scan_study"


@dataclass
class ScanPlan:
    name: str
    slug: str
    scan_root: Path
    manifest_path: Path | None
    film_stock: str
    film_type: str
    shot_year: str
    privacy: str
    root_dngs: list[str]
    root_dng_without_selected_candidates: list[str]
    candidate_counts: dict[str, int]
    missing_for_candidate_union: dict[str, list[str]]
    verifiable_stems: list[str]
    result_dir: Path
    result_complete: bool


@dataclass
class RunRecord:
    scan: str
    scan_root: str
    result_dir: str
    status: str
    command: list[str]
    seconds: float | None = None
    returncode: int | None = None


def slugify(text: str) -> str:
    safe = [char.lower() if char.isalnum() else "_" for char in text]
    return "_".join("".join(safe).split("_")) or "scan_set"


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_manifest(scan_root: Path) -> dict[str, Any]:
    path = scan_root / "scan_manifest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def discover_scan_roots(input_root: Path, explicit_roots: list[Path] | None) -> list[Path]:
    if explicit_roots:
        return [path.resolve() for path in explicit_roots]
    if not input_root.is_dir():
        return []
    roots = []
    for path in sorted(input_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        has_scan_data = (
            (path / "scan_manifest.json").is_file()
            or (path / "adc_jxl_dng").is_dir()
            or any(path.glob("*.dng"))
            or any(path.glob("*.DNG"))
        )
        if has_scan_data:
            roots.append(path.resolve())
    return roots


def root_dng_stems(scan_root: Path) -> list[str]:
    return sorted(
        {path.stem for path in scan_root.iterdir() if path.is_file() and path.suffix.lower() == ".dng"}
    )


def candidate_stems_by_level(scan_root: Path, levels: list[str]) -> dict[str, list[str]]:
    by_level: dict[str, list[str]] = {}
    for level in levels:
        folder = scan_root / "adc_jxl_dng" / level
        if folder.is_dir():
            by_level[level] = sorted(
                {path.stem for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".dng"}
            )
        else:
            by_level[level] = []
    return by_level


def result_complete(result_dir: Path) -> bool:
    required = [
        result_dir / "SUMMARY.md",
        result_dir / "metadata.csv",
        result_dir / "metadata_diff.csv",
        result_dir / "metadata_diff_summary.csv",
        result_dir / "summary.csv",
        result_dir / "patch_summary.csv",
    ]
    return all(path.is_file() and path.stat().st_size > 0 for path in required)


def build_scan_plan(scan_root: Path, levels: list[str], verification_root: Path) -> ScanPlan:
    manifest = load_manifest(scan_root)
    root_stems = root_dng_stems(scan_root)
    candidates = candidate_stems_by_level(scan_root, levels)
    root_set = set(root_stems)
    candidate_union = set().union(*(set(stems) for stems in candidates.values())) if candidates else set()
    candidate_union &= root_set
    verifiable = sorted(
        stem
        for stem in candidate_union
        if all(stem in set(candidates[level]) for level in levels)
    )
    missing = {
        level: sorted(candidate_union - set(candidates[level]))
        for level in levels
        if candidate_union - set(candidates[level])
    }
    slug = slugify(scan_root.name)
    return ScanPlan(
        name=scan_root.name,
        slug=slug,
        scan_root=scan_root,
        manifest_path=scan_root / "scan_manifest.json"
        if (scan_root / "scan_manifest.json").is_file()
        else None,
        film_stock=str(manifest.get("film_stock") or ""),
        film_type=str(manifest.get("film_type") or ""),
        shot_year=str(manifest.get("shot_year") or ""),
        privacy=str(manifest.get("privacy_default") or ""),
        root_dngs=root_stems,
        root_dng_without_selected_candidates=sorted(root_set - candidate_union),
        candidate_counts={level: len(candidates[level]) for level in levels},
        missing_for_candidate_union=missing,
        verifiable_stems=verifiable,
        result_dir=verification_root / f"{slug}_colorpatch",
        result_complete=result_complete(verification_root / f"{slug}_colorpatch"),
    )


def verification_command(plan: ScanPlan, args: argparse.Namespace, levels: list[str]) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts/run_dng_jxl_verification.py"),
        "--scan-root",
        str(plan.scan_root),
        "--out-dir",
        str(plan.result_dir),
        "--crop-size",
        str(args.crop_size),
        "--patch-size",
        str(args.patch_size),
        "--patch-color-space",
        args.patch_color_space,
        "--maxworkers",
        str(args.maxworkers),
    ]
    for level in levels:
        command.extend(["--level", level])
    for stem in plan.verifiable_stems:
        command.extend(["--source", stem])
    if args.panels:
        command.append("--panels")
    return command


def verification_env() -> dict[str, str]:
    env = os.environ.copy()
    local_deps = ROOT / ".deps/jxl_pydeps"
    if "JXL_PYDEPS" not in env and optional_deps_usable(local_deps):
        env["JXL_PYDEPS"] = str(local_deps)
    return env


def optional_deps_usable(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "tifffile" / "__init__.py").is_file()
        and (path / "imagecodecs" / "__init__.py").is_file()
    )


def run_verification(plan: ScanPlan, args: argparse.Namespace, levels: list[str]) -> RunRecord:
    command = verification_command(plan, args, levels)
    record = RunRecord(
        scan=plan.name,
        scan_root=relpath(plan.scan_root),
        result_dir=relpath(plan.result_dir),
        status="pending",
        command=command,
    )
    if not plan.verifiable_stems:
        record.status = "blocked_no_complete_adc_candidates"
        return record
    if plan.result_complete and not args.force:
        record.status = "skipped_existing"
        return record
    if args.dry_run:
        record.status = "dry_run"
        return record

    plan.result_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print(f"Running {plan.name}: {len(plan.verifiable_stems)} DNG source(s)", flush=True)
    completed = subprocess.run(command, check=False, env=verification_env())
    record.seconds = round(time.perf_counter() - started, 3)
    record.returncode = completed.returncode
    record.status = "ok" if completed.returncode == 0 and result_complete(plan.result_dir) else "failed"
    return record


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verification_highlights(result_dir: Path) -> list[dict[str, Any]]:
    metadata_rows = read_csv_rows(result_dir / "metadata.csv")
    patch_rows = read_csv_rows(result_dir / "patch_summary.csv")
    metadata_diff_rows = read_csv_rows(result_dir / "metadata_diff_summary.csv")
    if not metadata_rows or not patch_rows:
        return []

    source_by_stem: dict[str, float] = {}
    candidate_by_level: dict[str, float] = {}
    for row in metadata_rows:
        stem = row.get("stem", "")
        level = row.get("level", "")
        if stem and stem not in source_by_stem:
            source_by_stem[stem] = float(row.get("source_mib", "0") or 0)
        candidate_by_level[level] = candidate_by_level.get(level, 0.0) + float(
            row.get("candidate_mib", "0") or 0
        )
    source_mib = sum(source_by_stem.values())
    patch_by_key = {
        (row.get("level", ""), row.get("transform", "")): row
        for row in patch_rows
    }
    metadata_diff_by_level: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "expected_encoder_change": 0,
            "review_preservation_change": 0,
            "review_preservation_fields": set(),
        }
    )
    for row in metadata_diff_rows:
        level = row.get("level", "")
        interpretation = row.get("interpretation", "")
        try:
            changes = int(float(row.get("changes", "0") or 0))
        except ValueError:
            changes = 0
        if interpretation == "expected_encoder_change":
            metadata_diff_by_level[level]["expected_encoder_change"] += changes
        elif interpretation == "review_preservation_change":
            metadata_diff_by_level[level]["review_preservation_change"] += changes
            fields = {
                field.strip()
                for field in row.get("fields", "").split(",")
                if field.strip()
            }
            metadata_diff_by_level[level]["review_preservation_fields"].update(fields)

    highlights: list[dict[str, Any]] = []
    for level in sorted(candidate_by_level):
        identity = patch_by_key.get((level, "identity"), {})
        hard = patch_by_key.get((level, "negative_density_hard_print"), {})
        diff_summary = metadata_diff_by_level[level]
        highlights.append(
            {
                "level": level,
                "sources": len(source_by_stem),
                "source_gib": source_mib / 1024,
                "candidate_percent": (candidate_by_level[level] / source_mib * 100.0)
                if source_mib
                else 0.0,
                "identity_median_delta_e00": float(identity.get("median_delta_e00", "nan")),
                "hard_median_delta_e00": float(hard.get("median_delta_e00", "nan")),
                "hard_p95_delta_e00": float(hard.get("p95_delta_e00", "nan")),
                "hard_max_delta_e00": float(hard.get("max_delta_e00", "nan")),
                "hard_mean_rgb_rmse_16bit": float(hard.get("mean_error_rgb_rmse_16bit", "nan")),
                "metadata_expected_changes": diff_summary["expected_encoder_change"],
                "metadata_review_changes": diff_summary["review_preservation_change"],
                "metadata_review_fields": ", ".join(
                    sorted(diff_summary["review_preservation_fields"])
                )
                or "-",
            }
        )
    return highlights


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return relpath(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def write_index(index_dir: Path, plans: list[ScanPlan], records: list[RunRecord]) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    record_by_scan = {record.scan: record for record in records}
    payload = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "plans": [json_safe(asdict(plan)) for plan in plans],
        "runs": [asdict(record) for record in records],
        "highlights": {
            plan.name: verification_highlights(plan.result_dir)
            for plan in plans
        },
    }
    json_path = index_dir / "local_scan_study_index.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Local Scan Study Index",
        "",
        "Generated local output. This file is ignored by Git and may mention private scan folders.",
        "",
        f"Generated at UTC: `{generated_at}`",
        "",
        "## Scan Sets",
        "",
        "| Scan set | Film stock | Type | Year | Root DNGs | Verifiable DNGs | Result | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for plan in plans:
        record = record_by_scan.get(plan.name)
        status = record.status if record else "not_run"
        result = relpath(plan.result_dir) if plan.result_complete or status == "ok" else "-"
        lines.append(
            f"| `{plan.name}` | `{plan.film_stock or '-'}` | `{plan.film_type or '-'}` | "
            f"`{plan.shot_year or '-'}` | {len(plan.root_dngs)} | {len(plan.verifiable_stems)} | "
            f"`{result}` | `{status}` |"
        )

    lines.extend(["", "## Result Highlights", ""])
    lines.append(
        "| Scan set | Level | Sources | Source GiB | Candidate % | Identity med DeltaE00 | Hard med DeltaE00 | Hard p95 DeltaE00 | Hard max DeltaE00 | Hard RGB RMSE | Metadata review changes | Metadata review fields |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for plan in plans:
        for row in verification_highlights(plan.result_dir):
            lines.append(
                f"| `{plan.name}` | `{row['level']}` | {row['sources']} | "
                f"{row['source_gib']:.2f} | {row['candidate_percent']:.1f}% | "
                f"{row['identity_median_delta_e00']:.4f} | {row['hard_median_delta_e00']:.4f} | "
                f"{row['hard_p95_delta_e00']:.4f} | {row['hard_max_delta_e00']:.4f} | "
                f"{row['hard_mean_rgb_rmse_16bit']:.2f} | "
                f"{row['metadata_review_changes']} | `{row['metadata_review_fields']}` |"
            )

    lines.extend(["", "## Follow-Up Notes", ""])
    for plan in plans:
        if plan.root_dng_without_selected_candidates:
            joined = ", ".join(f"`{stem}`" for stem in plan.root_dng_without_selected_candidates)
            lines.append(f"- `{plan.name}` has root DNGs not covered by the selected ADC levels: {joined}.")
        if plan.missing_for_candidate_union:
            lines.append(f"- `{plan.name}` has incomplete selected ADC levels: `{plan.missing_for_candidate_union}`.")
    if not any(plan.root_dng_without_selected_candidates or plan.missing_for_candidate_union for plan in plans):
        lines.append("- No missing selected ADC candidates were detected.")

    md_path = index_dir / "LOCAL_SCAN_STUDY_INDEX.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local private scan-study verification queue for scan folders under input/."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="Folder containing local ignored scan-set directories. Defaults to input/.",
    )
    parser.add_argument(
        "--scan-root",
        type=Path,
        action="append",
        help="Specific scan folder to include. Repeatable. Defaults to all scan-like folders under input/.",
    )
    parser.add_argument("--verification-root", type=Path, default=DEFAULT_VERIFICATION_ROOT)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument(
        "--level",
        action="append",
        dest="levels",
        help="ADC level to require and verify. Repeatable. Defaults to project default levels.",
    )
    parser.add_argument("--crop-size", type=int, default=1536)
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument(
        "--patch-color-space",
        choices=["adobe-rgb", "display-p3", "prophoto-rgb", "srgb"],
        default="srgb",
    )
    parser.add_argument("--maxworkers", type=int, default=4)
    parser.add_argument("--panels", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rerun complete result directories.")
    parser.add_argument("--dry-run", action="store_true", help="Write no result files and run no verification.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        levels = [require_level(level) for level in (args.levels or DEFAULT_LEVELS)]
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.crop_size <= 0:
        raise SystemExit("--crop-size must be positive")
    if args.patch_size <= 0:
        raise SystemExit("--patch-size must be positive")
    if args.maxworkers <= 0:
        raise SystemExit("--maxworkers must be positive")

    roots = discover_scan_roots(args.input_root, args.scan_root)
    plans = [build_scan_plan(root, levels, args.verification_root) for root in roots]
    records = [run_verification(plan, args, levels) for plan in plans]
    if not args.dry_run:
        index_path = write_index(args.index_dir, plans, records)
        print(f"Wrote {index_path}", flush=True)
    else:
        for plan, record in zip(plans, records):
            print(
                f"{record.scan}: {record.status}; "
                f"verifiable={len(plan.verifiable_stems)}; "
                f"result_complete={plan.result_complete}; "
                f"result={relpath(plan.result_dir)}",
                flush=True,
            )

    failed = [record for record in records if record.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
