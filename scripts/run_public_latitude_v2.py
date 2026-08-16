from __future__ import annotations

import argparse
import hashlib
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
RUN_MANIFEST_NAME = "run_manifest.json"

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

PROVENANCE_CODE_FILES = [
    Path(__file__).resolve(),
    SCRIPTS / "run_public_latitude_stress.py",
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


def collect_tool_versions() -> dict[str, object]:
    cjxl = find_tool("cjxl", DEFAULT_CJXL)
    djxl = find_tool("djxl", DEFAULT_DJXL)
    return {
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
        "git": {
            "head": capture_command(["git", "rev-parse", "--verify", "HEAD"]),
            "status": capture_command(["git", "status", "--short"]),
        },
    }


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "sha256": sha256_file(path),
    }


def build_run_context(
    args: argparse.Namespace,
    versions: dict[str, object],
) -> dict[str, object]:
    tools = versions["tools"]
    assert isinstance(tools, dict)
    return {
        "pipeline": "public_latitude_stress_v2",
        "parameters": {
            "crop_size": args.crop_size,
            "crop": args.crop,
            "distance": list(args.distance),
            "effort": str(args.effort),
        },
        "inputs": [file_identity(path) for path in PUBLIC_V2_INPUTS],
        "code": [file_identity(path) for path in PROVENANCE_CODE_FILES],
        "environment": {
            "python": versions["python"],
            "platform": versions["platform"],
            "packages": versions["packages"],
            "tools": {
                "cjxl": tools.get("cjxl"),
                "djxl": tools.get("djxl"),
            },
        },
    }


def stress_artifacts(out_dir: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in out_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(out_dir)
        if relative.parts and relative.parts[0] == "panels":
            continue
        if path.name in {RUN_MANIFEST_NAME, "PANELS.md"} or path.name.endswith(".tmp"):
            continue
        artifacts[relative.as_posix()] = sha256_file(path)
    return dict(sorted(artifacts.items()))


def write_run_provenance(
    out_dir: Path,
    context: dict[str, object],
    versions: dict[str, object],
) -> None:
    required = [out_dir / "metrics.csv", out_dir / "metrics.json"]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "stress run completed without required result files: "
            + ", ".join(str(path) for path in missing)
        )

    versions_path = out_dir / "tool_versions.json"
    write_json_atomic(versions_path, versions)
    manifest_path = out_dir / RUN_MANIFEST_NAME
    write_json_atomic(
        manifest_path,
        {
            "schema_version": 1,
            "context": context,
            "artifacts": stress_artifacts(out_dir),
        },
    )
    print(f"Wrote {versions_path}")
    print(f"Wrote {manifest_path}")


def validate_reuse(out_dir: Path, expected_context: dict[str, object]) -> None:
    manifest_path = out_dir / RUN_MANIFEST_NAME
    if not manifest_path.is_file():
        raise SystemExit(
            f"cannot reuse stress results: {manifest_path} is missing; "
            "rerun without --skip-stress"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"cannot reuse stress results: invalid {manifest_path}: {exc}") from exc

    if manifest.get("schema_version") != 1 or manifest.get("context") != expected_context:
        raise SystemExit(
            "cannot reuse stress results: run context does not match; "
            "rerun without --skip-stress"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("cannot reuse stress results: manifest has no artifact map")
    required = {"metrics.csv", "metrics.json", "tool_versions.json"}
    missing_records = sorted(required - set(artifacts))
    if missing_records:
        raise SystemExit(
            "cannot reuse stress results: manifest does not cover "
            + ", ".join(missing_records)
        )

    for relative, expected_sha256 in artifacts.items():
        candidate = Path(relative)
        if not isinstance(relative, str) or not isinstance(expected_sha256, str):
            raise SystemExit("cannot reuse stress results: malformed artifact record")
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SystemExit(f"cannot reuse stress results: unsafe artifact path {relative}")
        path = out_dir / candidate
        if not path.is_file():
            raise SystemExit(f"cannot reuse stress results: missing artifact {relative}")
        if sha256_file(path) != expected_sha256:
            raise SystemExit(f"cannot reuse stress results: changed artifact {relative}")

    print(f"Validated reusable stress results from {manifest_path}")


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
        "--effort",
        str(args.effort),
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
    parser.add_argument("--effort", default="7", help="cjxl effort, usually 1-9")
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
    versions = collect_tool_versions()
    context = build_run_context(args, versions)
    if args.skip_stress:
        validate_reuse(args.out_dir, context)
    else:
        run_stress(args)
        write_run_provenance(args.out_dir, context, versions)
    if not args.skip_panels:
        run_panels(args)
    if args.publish_figures:
        publish_figures(args.out_dir, ROOT / "docs/figures/public-latitude-v2")

    print(f"Public v2 output: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
