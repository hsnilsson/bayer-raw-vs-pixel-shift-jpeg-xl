from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_CJXL = ROOT / "work/jxl-tools/bin/cjxl.exe"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"

PUBLIC_V2_INPUTS = [
    ROOT / "testdata/fadgi_opendice/negative_35mm_1/Negative_35mm_ICC.tif",
    ROOT / "testdata/fadgi_opendice/negative_35mm_2/Negative 35mm_2.tif",
    ROOT / "testdata/fadgi_opendice/positive_35mm/Positive 35mm.tif",
    ROOT / "testdata/library_of_congress/highsmith/golden-gate-bridge-san-francisco-california.tif",
    ROOT
    / "testdata/library_of_congress/highsmith/roadside-wildflowers-and-some-dandelion-remnants-in-bent-county-colorado.tif",
    ROOT
    / "testdata/library_of_congress/highsmith/the-caloosahatchee-bridge-carries-us-highway-41-over-the-caloosahatchee-river-in.tif",
]

PANEL_TRANSFORMS = [
    "identity",
    "negative_density_print",
    "negative_density_hard_print",
]

SELECTED_FIGURES = [
    (
        "negative-35mm-2",
        "0.05",
        "negative_density_hard_print",
        "fadgi-negative35mm2-d005-density-hard-print.png",
    ),
    (
        "negative-35mm-2",
        "0.10",
        "negative_density_hard_print",
        "fadgi-negative35mm2-d010-density-hard-print.png",
    ),
    (
        "golden-gate-bridge-san-francisco-california",
        "0.05",
        "negative_density_hard_print",
        "loc-golden-gate-d005-density-hard-print.png",
    ),
    (
        "golden-gate-bridge-san-francisco-california",
        "0.10",
        "negative_density_hard_print",
        "loc-golden-gate-d010-density-hard-print.png",
    ),
    (
        "roadside-wildflowers-and-some-dandelion-remnants-in-bent-county-colorado",
        "0.05",
        "negative_density_hard_print",
        "loc-wildflowers-d005-density-hard-print.png",
    ),
    (
        "roadside-wildflowers-and-some-dandelion-remnants-in-bent-county-colorado",
        "0.10",
        "negative_density_hard_print",
        "loc-wildflowers-d010-density-hard-print.png",
    ),
]


def run_command(args: list[str]) -> None:
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def find_tool(name: str, fallback: Path) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if fallback.exists():
        return str(fallback)
    return None


def capture_command(args: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except OSError as exc:
        return {"command": args, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"command": args, "error": "timed out"}
    return {
        "command": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def git_snapshot() -> dict[str, object]:
    commit = capture_command(["git", "rev-parse", "--verify", "HEAD"])
    commit_value = commit["stdout"] if commit.get("returncode") == 0 else None
    branch = capture_command(["git", "branch", "--show-current"])
    return {
        "commit": commit_value,
        "commit_available": commit_value is not None,
        "branch": branch["stdout"] if branch.get("returncode") == 0 else None,
        "status_short": capture_command(["git", "status", "--short"]),
    }


def write_tool_versions(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cjxl = find_tool("cjxl", DEFAULT_CJXL)
    djxl = find_tool("djxl", DEFAULT_DJXL)
    versions: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "packages": {
            "numpy": package_version("numpy"),
            "Pillow": package_version("Pillow"),
            "tifffile": package_version("tifffile"),
        },
        "tools": {
            "cjxl": {
                "path": cjxl,
                "version": capture_command([cjxl, "--version"]) if cjxl else None,
            },
            "djxl": {
                "path": djxl,
                "version": capture_command([djxl, "--version"]) if djxl else None,
            },
            "git": capture_command(["git", "--version"]),
        },
        "git": git_snapshot(),
    }
    path = out_dir / "tool_versions.json"
    path.write_text(json.dumps(versions, indent=2), encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")


def distance_token(distance: str) -> str:
    return distance.replace(".", "_")


def require_inputs() -> None:
    missing = [path for path in PUBLIC_V2_INPUTS if not path.exists()]
    if not missing:
        return
    print("Missing public v2 input files:", file=sys.stderr)
    for path in missing:
        print(f"  {path.relative_to(ROOT)}", file=sys.stderr)
    print("\nDownload public data first:", file=sys.stderr)
    print("  python scripts\\download_testdata.py --include-loc --loc-count 3", file=sys.stderr)
    raise SystemExit(2)


def run_stress(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(SCRIPTS / "run_public_latitude_stress.py"),
        *[str(path) for path in PUBLIC_V2_INPUTS],
        "--crop-size",
        str(args.crop_size),
        "--crop",
        args.crop,
        "--out-dir",
        str(args.out_dir),
    ]
    for distance in args.distance:
        cmd.extend(["--distance", distance])
    run_command(cmd)


def run_panels(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(SCRIPTS / "make_public_crop_panels.py"),
        str(args.out_dir),
        "--panel-size",
        str(args.panel_size),
        "--diff-gain",
        str(args.diff_gain),
        "--transforms",
        *PANEL_TRANSFORMS,
    ]
    run_command(cmd)


def publish_figures(results_dir: Path, figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    for image_id, distance, transform, filename in SELECTED_FIGURES:
        source = (
            results_dir
            / "panels"
            / image_id
            / f"d{distance_token(distance)}_{transform}.png"
        )
        if not source.exists():
            raise FileNotFoundError(f"missing selected panel: {source}")
        target = figures_dir / filename
        shutil.copy2(source, target)
        print(f"Copied {target.relative_to(ROOT)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the public latitude-stress v2 pipeline from the bundled public test set."
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/public_latitude_stress_v2")
    parser.add_argument("--crop-size", type=int, default=2048)
    parser.add_argument("--crop", choices=["center", "upper-left", "lower-right"], default="center")
    parser.add_argument(
        "--distance",
        action="append",
        default=None,
        help="JPEG XL distance; repeatable. Defaults to 0.03, 0.05, and 0.10.",
    )
    parser.add_argument("--panel-size", type=int, default=512)
    parser.add_argument("--diff-gain", type=float, default=64.0)
    parser.add_argument("--skip-stress", action="store_true", help="reuse existing metrics and decoded files")
    parser.add_argument("--skip-panels", action="store_true", help="reuse existing panel images")
    parser.add_argument(
        "--publish-figures",
        action="store_true",
        help="copy the selected v2 panels into docs/figures/public-latitude-v2",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.out_dir = Path(args.out_dir)
    if args.distance is None:
        args.distance = ["0.03", "0.05", "0.10"]

    require_inputs()
    write_tool_versions(args.out_dir)
    if not args.skip_stress:
        run_stress(args)
    if not args.skip_panels:
        run_panels(args)
    if args.publish_figures:
        publish_figures(args.out_dir, ROOT / "docs/figures/public-latitude-v2")

    print(f"Public v2 output: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
