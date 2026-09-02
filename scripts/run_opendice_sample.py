from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "testdata/fadgi_opendice/Config_materials2023.txt"
DEFAULT_IMAGE = ROOT / "testdata/fadgi_opendice/negative_35mm_2/Negative 35mm_2.tif"
DEFAULT_PROFILE = ROOT / "testdata/fadgi_opendice/negative_35mm_2/Profile_35mm_Negative2.txt"
DEFAULT_OUTPUT = ROOT / "results/opendice_sample_measurement"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_command(
    executable: Path,
    config: Path,
    material: int,
    stars: int,
    image: Path,
    target_option: int,
    profile: Path,
    export_rgb: bool,
) -> list[str]:
    command = [
        str(executable.resolve()),
        str(config.resolve()),
        str(material),
        str(stars),
        str(image.resolve()),
        str(target_option),
        str(profile.resolve()),
    ]
    if export_rgb:
        command.append("-e")
    return command


def checked_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")
    return path


def manifest_file(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def file_state(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run FADGI OpenDICE 3.00 against its public Negative 35mm (2) sample target."
    )
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path(os.environ["OPENDICE_COMMAND"]) if os.environ.get("OPENDICE_COMMAND") else None,
        help="Path to OpenDICECommandv3.0_win.exe; may also be set with OPENDICE_COMMAND.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--material", type=int, default=11, help="OpenDICE material 11: photographic negatives 35mm to 4x5.")
    parser.add_argument("--stars", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--target-option", type=int, default=12, help="OpenDICE target 12: Negative Small 35mm 2.")
    parser.add_argument("--luminance-only", action="store_true", help="Omit -e; default exports all RGB components.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.executable is None:
        raise SystemExit(
            "OpenDICE executable not configured. Pass --executable or set OPENDICE_COMMAND. "
            "OpenDICE 3.00 also requires MATLAB Runtime 9.13 (R2022b)."
        )

    executable = checked_file(args.executable, "OpenDICE executable")
    config = checked_file(args.config, "materials configuration")
    image = checked_file(args.image, "sample target image")
    profile = checked_file(args.profile, "sample target profile")
    command = build_command(
        executable,
        config,
        args.material,
        args.stars,
        image,
        args.target_option,
        profile,
        not args.luminance_only,
    )
    print(subprocess.list2cmdline(command))
    if args.dry_run:
        return 0

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {
        path.resolve(): file_state(path)
        for path in output_dir.iterdir()
        if path.is_file()
    }
    completed = subprocess.run(
        command,
        cwd=output_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    log_path = output_dir / "opendice.log"
    log_path.write_text(combined_output, encoding="utf-8")
    generated = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and path != log_path
        and before.get(path.resolve()) != file_state(path)
    )
    runtime_missing = "mclmcrrt9_13.dll" in combined_output or "MATLAB Runtime" in combined_output
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "OpenDICE public sample-target analysis; not a measurement of the project's camera-scanning rig",
        "command": command,
        "parameters": {
            "material": args.material,
            "stars": args.stars,
            "target_option": args.target_option,
            "export_rgb": not args.luminance_only,
        },
        "inputs": [manifest_file(path) for path in (config, image, profile)],
        "tool": manifest_file(executable),
        "returncode": completed.returncode,
        "matlab_runtime_9_13_missing": runtime_missing,
        "outputs": [manifest_file(path) for path in generated],
        "log": str(log_path),
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if completed.returncode != 0:
        if runtime_missing:
            raise SystemExit(
                "OpenDICE could not start because MATLAB Runtime 9.13 (R2022b) is missing. "
                f"See {log_path}."
            )
        raise SystemExit(f"OpenDICE failed with exit code {completed.returncode}; see {log_path}.")
    if not generated:
        raise SystemExit(f"OpenDICE exited successfully but produced no result files in {output_dir}.")

    print(f"Wrote {output_dir / 'run_manifest.json'}")
    for path in generated:
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
