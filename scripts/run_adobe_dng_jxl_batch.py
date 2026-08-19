from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ADC = Path(r"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe")
LEVEL_DISTANCES = {
    "d003": "0.03",
    "d005": "0.05",
    "d010": "0.10",
}
DEFAULT_LEVELS = ["lossless", "d003", "d005", "d010"]


@dataclass
class ConversionRecord:
    level: str
    source: str
    output: str
    status: str
    command: list[str]
    returncode: int | None = None
    seconds: float | None = None
    stdout: str | None = None
    stderr: str | None = None


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def source_from_spec(scan_root: Path, spec: str) -> Path:
    candidate = Path(spec)
    if candidate.suffix.lower() == ".dng":
        path = candidate if candidate.is_absolute() else scan_root / candidate
    else:
        path = scan_root / f"{spec}.dng"
    return path


def source_dngs(scan_root: Path, requested: list[str] | None = None) -> list[Path]:
    if requested:
        sources = [source_from_spec(scan_root, spec) for spec in requested]
        missing = [source for source in sources if not source.is_file()]
        if missing:
            joined = ", ".join(str(source) for source in missing)
            raise FileNotFoundError(f"requested source DNG(s) not found: {joined}")
        return sources
    return sorted(path for path in scan_root.glob("*.dng") if path.is_file())


def output_path(scan_root: Path, level: str, source: Path) -> Path:
    return scan_root / "adc_jxl_dng" / level / source.name


def command_for_conversion(
    adc: Path,
    level: str,
    source: Path,
    destination: Path,
    *,
    effort: int,
) -> list[str]:
    command = [str(adc)]
    if level == "lossless":
        command.append("-losslessJXL")
    else:
        command.extend(["-lossy", "-jxl_effort", str(effort), "-jxl_distance", LEVEL_DISTANCES[level]])
    command.extend(["-d", str(destination), str(source)])
    return command


def run_conversion(
    *,
    scan_root: Path,
    adc: Path,
    level: str,
    source: Path,
    effort: int,
    dry_run: bool,
) -> ConversionRecord:
    destination = scan_root / "adc_jxl_dng" / level
    output = output_path(scan_root, level, source)
    command = command_for_conversion(adc, level, source, destination, effort=effort)
    record = ConversionRecord(
        level=level,
        source=relpath(source, scan_root),
        output=relpath(output, scan_root),
        status="pending",
        command=command,
    )

    if output.exists():
        record.status = "skipped_existing"
        return record
    if dry_run:
        record.status = "dry_run"
        return record

    destination.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    record.seconds = round(time.perf_counter() - started, 3)
    record.returncode = completed.returncode
    record.stdout = completed.stdout.strip()
    record.stderr = completed.stderr.strip()
    if completed.returncode != 0:
        record.status = "failed"
    elif not output.exists() or output.stat().st_size == 0:
        record.status = "missing_output"
    else:
        record.status = "ok"
    return record


def build_run_manifest(
    *,
    scan_root: Path,
    adc: Path,
    levels: list[str],
    effort: int,
    records: list[ConversionRecord],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan_root": str(scan_root),
        "adobe_dng_converter": str(adc),
        "levels": levels,
        "jxl_effort": effort,
        "records": [asdict(record) for record in records],
        "summary": {
            "ok": sum(record.status == "ok" for record in records),
            "skipped_existing": sum(record.status == "skipped_existing" for record in records),
            "dry_run": sum(record.status == "dry_run" for record in records),
            "failed": sum(record.status == "failed" for record in records),
            "missing_output": sum(record.status == "missing_output" for record in records),
        },
    }


def write_manifest(scan_root: Path, manifest: dict[str, Any]) -> Path:
    path = scan_root / "adc_jxl_dng" / "run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Adobe DNG Converter DNG/JPEG XL batches for a scan folder."
    )
    parser.add_argument("scan_root", type=Path)
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Source stem, DNG filename, or DNG path to convert. Repeatable. "
            "Defaults to all root-level DNG files."
        ),
    )
    parser.add_argument("--adc", type=Path, default=DEFAULT_ADC)
    parser.add_argument("--levels", nargs="+", default=DEFAULT_LEVELS, choices=DEFAULT_LEVELS)
    parser.add_argument("--effort", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scan_root = args.scan_root.resolve()
    if not scan_root.is_dir():
        raise FileNotFoundError(f"scan root does not exist: {scan_root}")
    if not args.adc.is_file():
        raise FileNotFoundError(f"Adobe DNG Converter not found: {args.adc}")

    sources = source_dngs(scan_root, args.source)
    if not sources:
        raise FileNotFoundError(f"no root-level DNG files found in {scan_root}")

    records: list[ConversionRecord] = []
    total = len(sources) * len(args.levels)
    current = 0
    for level in args.levels:
        for source in sources:
            current += 1
            print(f"[{current}/{total}] {level} {source.name}", flush=True)
            record = run_conversion(
                scan_root=scan_root,
                adc=args.adc,
                level=level,
                source=source,
                effort=args.effort,
                dry_run=args.dry_run,
            )
            print(f"  {record.status}", flush=True)
            records.append(record)

    manifest = build_run_manifest(
        scan_root=scan_root,
        adc=args.adc,
        levels=list(args.levels),
        effort=args.effort,
        records=records,
    )
    manifest_path = write_manifest(scan_root, manifest)
    print(f"Wrote {manifest_path}")

    failed = [record for record in records if record.status in {"failed", "missing_output"}]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
