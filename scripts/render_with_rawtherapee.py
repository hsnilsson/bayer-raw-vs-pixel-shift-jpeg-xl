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
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_local_scan_study as local_study  # noqa: E402
from jxl_levels import DEFAULT_LEVELS, require_level  # noqa: E402


DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_PROFILE = ROOT / "profiles/rawtherapee/neutral-render.pp3"


@dataclass
class RenderJob:
    scan_set: str
    set_id: str
    role: str
    level: str
    source: str
    output: str
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


def find_rawtherapee(explicit: Path | None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(str(explicit))
    candidates.extend(
        [
            "rawtherapee-cli.exe",
            "rawtherapee-cli",
            r"C:\Program Files\RawTherapee\5.12\rawtherapee-cli.exe",
            r"C:\Program Files\RawTherapee\5.11\rawtherapee-cli.exe",
            r"C:\Program Files\RawTherapee\5.10\rawtherapee-cli.exe",
            r"C:\Program Files\RawTherapee\5.9\rawtherapee-cli.exe",
        ]
    )
    for candidate in candidates:
        found = shutil.which(candidate) if "\\" not in candidate and "/" not in candidate else None
        if found:
            return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    raise SystemExit(
        "Could not find rawtherapee-cli. Pass --rawtherapee with the full path "
        "to rawtherapee-cli.exe."
    )


def output_path(output_root: Path, scan_set: str, set_id: str, role: str, level: str) -> Path:
    folder = output_root / local_study.slugify(scan_set) / set_id
    if role == "adc_jxl_dng":
        return folder / "adc_jxl_dng" / level / "ps16_candidate.tif"
    return folder / f"{role}.tif"


def render_command(rawtherapee: str, source: Path, output: Path, profile: Path) -> list[str]:
    return [
        rawtherapee,
        "-Y",
        "-p",
        str(profile),
        "-o",
        str(output),
        "-t",
        "-b16",
        "-c",
        str(source),
    ]


def collect_jobs(scan_root: Path, output_root: Path, levels: list[str]) -> list[tuple[Path, Path, RenderJob]]:
    manifest = load_manifest(scan_root)
    if not manifest:
        return []
    scan_set = manifest.get("scan_root_name") or scan_root.name
    jobs: list[tuple[Path, Path, RenderJob]] = []
    for capture in manifest.get("capture_sets", []):
        set_id = capture.get("set_id", "")
        sources: list[tuple[str, str, str]] = []
        if capture.get("single_raw"):
            sources.append(("raw61", "", capture["single_raw"]))
        if capture.get("pixelshift16_dng"):
            sources.append(("ps16", "", capture["pixelshift16_dng"]))
            for level in levels:
                sources.append(
                    (
                        "adc_jxl_dng",
                        level,
                        str(Path("adc_jxl_dng") / level / capture["pixelshift16_dng"]),
                    )
                )
        for role, level, relative in sources:
            source = scan_root / relative
            output = output_path(output_root, scan_set, set_id, role, level)
            status = "pending" if source.is_file() else "missing_source"
            notes = "" if source.is_file() else f"missing source: {relpath(source)}"
            jobs.append(
                (
                    source,
                    output,
                    RenderJob(
                        scan_set=scan_set,
                        set_id=set_id,
                        role=role,
                        level=level,
                        source=relpath(source),
                        output=relpath(output),
                        status=status,
                        notes=notes,
                    ),
                )
            )
    return jobs


def write_index(rows: list[RenderJob], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "rawtherapee_render_index.csv"
    json_path = output_root / "rawtherapee_render_index.json"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
    json_path.write_text(
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
        description="Render RAW61, PS16, and ADC DNG/JXL candidates with one fixed RawTherapee profile."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--rawtherapee", type=Path, default=None)
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.profile.is_file():
        raise SystemExit(
            f"Missing RawTherapee profile: {relpath(args.profile)}. "
            "Create a fixed neutral .pp3 first, then rerun with --profile."
        )
    levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
    rawtherapee = find_rawtherapee(args.rawtherapee)
    rows: list[RenderJob] = []
    for scan_root in discover_scan_roots(args.input_root, args.scan_root):
        for source, output, job in collect_jobs(scan_root, args.output_root, levels):
            if job.status == "missing_source":
                rows.append(job)
                continue
            if output.is_file() and not args.force:
                job.status = "already_exists"
                rows.append(job)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            cmd = render_command(rawtherapee, source, output, args.profile)
            if args.dry_run:
                job.status = "dry_run"
                job.notes = " ".join(cmd)
            else:
                result = subprocess.run(
                    cmd,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if result.returncode:
                    job.status = "render_failed"
                    output.unlink(missing_ok=True)
                    message = (result.stdout + result.stderr).strip().splitlines()
                    job.notes = message[-1] if message else f"exit code {result.returncode}"
                else:
                    job.status = "rendered"
            rows.append(job)

    write_index(rows, args.output_root)
    print(f"Wrote {len(rows)} render job row(s) to {relpath(args.output_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
