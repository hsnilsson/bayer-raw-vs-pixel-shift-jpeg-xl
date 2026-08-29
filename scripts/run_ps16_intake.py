from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from create_scan_manifest import read_raw_pixelshift_groups  # noqa: E402
from jxl_levels import distance_for_level, require_level  # noqa: E402


DEFAULT_PS2DNG = Path(r"C:\Program Files\LibRaw\PixelShift2DNG\PixelShift2DNG.exe")
DEFAULT_ADC = Path(r"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe")
DEFAULT_EXIFTOOL = Path(r"C:\Program Files\ExifTool\ExifTool.exe")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def complete_ps16_groups(scan_root: Path, exiftool: Path) -> list[dict[str, Any]]:
    groups, status = read_raw_pixelshift_groups(scan_root, exiftool=str(exiftool))
    if status["status"] != "ok":
        raise RuntimeError(f"ExifTool grouping failed: {status}")
    return [
        {
            "group_id": group.group_id,
            "raw_files": group.raw_files,
            "first_raw": group.first_raw,
            "last_raw": group.last_raw,
            "expected_dng": expected_dng_name(group.first_raw, group.last_raw),
        }
        for group in groups
        if group.mode == "pixelshift16"
        and group.raw_files_present == 16
        and not group.missing_shots
    ]


def expected_dng_name(first_raw: str | None, last_raw: str | None) -> str:
    if not first_raw or not last_raw:
        raise ValueError("complete group has no first/last raw filename")
    return f"{Path(first_raw).stem}-{Path(last_raw).stem}.dng"


def wait_for_stable_files(paths: list[Path], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    previous: dict[Path, int] = {}
    stable_passes = 0
    while time.monotonic() < deadline:
        current = {path: path.stat().st_size for path in paths if path.is_file()}
        if len(current) == len(paths) and all(size > 0 for size in current.values()):
            if current == previous:
                stable_passes += 1
                if stable_passes >= 3:
                    return
            else:
                stable_passes = 0
        previous = current
        time.sleep(2)
    missing = [str(path) for path in paths if not path.is_file()]
    raise TimeoutError(f"PixelShift2DNG output did not stabilize; missing={missing}")


def launch_pixelshift(scan_root: Path, executable: Path) -> None:
    helper = ROOT / "scripts" / "invoke_pixelshift2dng.ps1"
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Executable",
            str(executable),
            "-InputFolder",
            str(scan_root),
        ],
        check=True,
    )


def adc_command(adc: Path, source: Path, destination: Path, level: str, effort: int) -> list[str]:
    command = [str(adc)]
    if level == "lossless":
        command.append("-losslessJXL")
    else:
        command.extend(
            ["-lossy", "-jxl_effort", str(effort), "-jxl_distance", distance_for_level(level) or ""]
        )
    command.extend(["-d", str(destination), str(source)])
    return command


def validate_dng(path: Path, exiftool: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(exiftool), "-json", "-validate", "-ImageWidth", "-ImageHeight", str(path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    rows = json.loads(completed.stdout or "[]")
    row = rows[0] if rows else {}
    width = int(row.get("ImageWidth") or 0)
    height = int(row.get("ImageHeight") or 0)
    return {
        "returncode": completed.returncode,
        "width": width,
        "height": height,
        "validation": row.get("Validate"),
        "ok": completed.returncode == 0 and width > 0 and height > 0 and path.stat().st_size > 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create PS16 DNG files, rewrite them as JPEG XL DNG, and verify without deleting sources."
    )
    parser.add_argument("scan_root", type=Path)
    parser.add_argument("--level", default="d005")
    parser.add_argument("--effort", type=int, default=7)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--pixelshift2dng", type=Path, default=DEFAULT_PS2DNG)
    parser.add_argument("--adc", type=Path, default=DEFAULT_ADC)
    parser.add_argument("--exiftool", type=Path, default=DEFAULT_EXIFTOOL)
    parser.add_argument("--skip-pixelshift", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hash", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scan_root = args.scan_root.resolve()
    level = require_level(args.level)
    for path, label in ((scan_root, "scan folder"), (args.adc, "Adobe DNG Converter"), (args.exiftool, "ExifTool")):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")
    if not args.skip_pixelshift and not args.pixelshift2dng.is_file():
        raise FileNotFoundError(f"PixelShift2DNG not found: {args.pixelshift2dng}")

    groups = complete_ps16_groups(scan_root, args.exiftool)
    if not groups:
        raise RuntimeError("No complete 16-shot PixelShift groups found.")
    sources = [scan_root / group["expected_dng"] for group in groups]
    missing_sources = [source for source in sources if not source.is_file()]

    print(f"Found {len(groups)} complete PS16 group(s).")
    if args.dry_run:
        for group in groups:
            print(f"  {group['group_id']}: {group['expected_dng']}")
        return 0

    if missing_sources and not args.skip_pixelshift:
        launch_pixelshift(scan_root, args.pixelshift2dng)
        wait_for_stable_files(missing_sources, args.timeout_seconds)
    elif missing_sources:
        raise FileNotFoundError(f"Missing PS16 DNG output(s): {missing_sources}")

    destination = scan_root / "adc_jxl_dng" / level
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for source in sources:
        output = destination / source.name
        command = adc_command(args.adc, source, destination, level, args.effort)
        if not output.is_file():
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError(f"Adobe DNG Converter failed for {source.name}: {completed.stderr}")
        verification = validate_dng(output, args.exiftool)
        if not verification["ok"]:
            raise RuntimeError(f"Verification failed for {output}: {verification}")
        records.append(
            {
                "group_id": next(group["group_id"] for group in groups if group["expected_dng"] == source.name),
                "source_dng": source.name,
                "jxl_dng": output.relative_to(scan_root).as_posix(),
                "level": level,
                "bytes": output.stat().st_size,
                "sha256": sha256_file(output) if args.hash else None,
                "verification": verification,
                "source_raws_retained": True,
            }
        )
        print(f"Verified {output.name}: {verification['width']}x{verification['height']}")

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan_root": str(scan_root),
        "policy": "no_source_deletion",
        "records": records,
    }
    manifest_path = scan_root / "ps16_intake_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
