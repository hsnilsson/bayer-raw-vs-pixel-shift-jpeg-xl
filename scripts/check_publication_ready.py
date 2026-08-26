from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GIT_SAFE_DIRECTORY = ROOT.as_posix()
WARN_SIZE = 50 * 1024 * 1024
IGNORED_LINK_DIRS = {".git", "results", "outputs", "work", "input", ".agents", ".codex"}
REQUIRED_FILES = [
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "THIRD_PARTY_DATA.md",
    "REPRODUCIBILITY.md",
    "RELATED_WORK.md",
    "RESEARCH_PLAN.md",
    "ARCHIVAL_VALUE_METRICS.md",
    "TEST_MATERIAL_STRATEGY.md",
    "CONCLUSIONS.md",
    "NEXT_STEPS.md",
    "README.md",
    "RESULTS.md",
    "METHODOLOGY.md",
    "LIMITATIONS.md",
    "TESTDATA.md",
    "scripts/audit_publication_safety.py",
    "scripts/download_testdata.py",
    "scripts/inspect_dng_jxl_color_path.py",
    "scripts/jxl_levels.py",
    "scripts/run_public_latitude_stress.py",
    "scripts/make_public_crop_panels.py",
    "scripts/run_public_latitude_v2.py",
    "scripts/create_scan_manifest.py",
    "scripts/run_adobe_dng_jxl_batch.py",
    "scripts/run_dng_jxl_verification.py",
    "scripts/run_local_scan_study.py",
    "scripts/run_storage_budget_index.py",
    "scripts/render_with_rawtherapee.py",
    "scripts/register_raw61_to_ps16.py",
    "scripts/run_raw61_loss_metrics.py",
    "scripts/run_structure_metrics.py",
    "scripts/run_rendered_ps16_jxl_matrix.py",
    "scripts/run_archival_break_even.py",
    "src/break_even_image_tools.py",
    "profiles/rawtherapee/README.md",
    "tests/test_review_fixes.py",
]
PYTHON_FILES = [
    "scripts/audit_publication_safety.py",
    "scripts/download_testdata.py",
    "scripts/inspect_dng_jxl_color_path.py",
    "scripts/jxl_levels.py",
    "scripts/run_public_latitude_stress.py",
    "scripts/make_public_crop_panels.py",
    "scripts/run_public_latitude_v2.py",
    "scripts/create_scan_manifest.py",
    "scripts/run_adobe_dng_jxl_batch.py",
    "scripts/run_dng_jxl_verification.py",
    "scripts/run_local_scan_study.py",
    "scripts/run_storage_budget_index.py",
    "scripts/render_with_rawtherapee.py",
    "scripts/register_raw61_to_ps16.py",
    "scripts/run_raw61_loss_metrics.py",
    "scripts/run_structure_metrics.py",
    "scripts/run_rendered_ps16_jxl_matrix.py",
    "scripts/run_archival_break_even.py",
    "scripts/check_publication_ready.py",
    "src/break_even_image_tools.py",
    "src/jxl_archive_test.py",
    "tests/test_break_even_pipeline.py",
    "tests/test_review_fixes.py",
]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def check_required_files() -> Check:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        return Check("required files", False, "missing: " + ", ".join(missing))
    return Check("required files", True, f"{len(REQUIRED_FILES)} files present")


def check_python_syntax() -> Check:
    failures: list[str] = []
    for relative in PYTHON_FILES:
        path = ROOT / relative
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        return Check("python syntax", False, "\n".join(failures))
    return Check("python syntax", True, f"{len(PYTHON_FILES)} files parsed")


def check_unit_tests() -> Check:
    result = run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        return Check("unit tests", False, output)
    summary = output.splitlines()[-1] if output else "tests passed"
    return Check("unit tests", True, summary)


def check_markdown_links() -> Check:
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    missing: list[str] = []
    for md in ROOT.rglob("*.md"):
        rel = md.relative_to(ROOT)
        if set(rel.parts) & IGNORED_LINK_DIRS:
            continue
        text = md.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            target = match.group(1).split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = target.replace("%20", " ")
            path = (md.parent / target).resolve()
            try:
                path.relative_to(ROOT)
            except ValueError:
                continue
            if not path.exists():
                missing.append(f"{rel.as_posix()} -> {target}")
    if missing:
        return Check("markdown links", False, "\n".join(missing))
    return Check("markdown links", True, "local links resolve")


def git_lfs_available() -> bool:
    return run_command(["git", "lfs", "version"]).returncode == 0


def is_lfs_tracked(path: Path) -> bool:
    result = run_command([
        "git",
        "-c",
        f"safe.directory={GIT_SAFE_DIRECTORY}",
        "check-attr",
        "filter",
        "--",
        str(path.relative_to(ROOT)),
    ])
    return result.returncode == 0 and result.stdout.strip().endswith("filter: lfs")


def check_large_testdata_lfs() -> Check:
    large_files = [
        path for path in (ROOT / "testdata").rglob("*")
        if path.is_file() and path.stat().st_size > WARN_SIZE
    ]
    not_lfs = [path.relative_to(ROOT).as_posix() for path in large_files if not is_lfs_tracked(path)]
    if not_lfs:
        return Check("large testdata lfs", False, "not LFS tracked: " + ", ".join(not_lfs))
    detail = f"{len(large_files)} large files marked for LFS"
    if not git_lfs_available():
        return Check("large testdata lfs", False, detail + "; git lfs is not available")
    return Check("large testdata lfs", True, detail)


def check_source_sidecars() -> Check:
    missing: list[str] = []
    for path in (ROOT / "testdata").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".tif", ".tiff", ".txt"} and not path.name.endswith(".source.json"):
            sidecar = path.with_name(path.name + ".source.json")
            if not sidecar.exists():
                missing.append(path.relative_to(ROOT).as_posix())
    if missing:
        return Check("testdata sidecars", False, "missing sidecar: " + ", ".join(missing))
    return Check("testdata sidecars", True, "downloaded files have source sidecars")


def check_run_provenance() -> Check:
    results_dir = ROOT / "results/public_latitude_stress_v2"
    required_files = ["metrics.csv", "metrics.json", "tool_versions.json", "run_manifest.json"]
    present = [name for name in required_files if (results_dir / name).exists()]
    if not present:
        return Check("run provenance", True, "no local v2 result directory to check")
    missing = [name for name in required_files if name not in present]
    if missing:
        return Check("run provenance", False, "missing: " + ", ".join(missing))
    return Check("run provenance", True, "v2 run manifest exists")


def check_publication_audit(include_ignored: bool) -> Check:
    args = [sys.executable, str(ROOT / "scripts/audit_publication_safety.py")]
    if include_ignored:
        args.append("--include-ignored")
    result = run_command(args)
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        return Check("publication audit", False, output)
    summary = output.splitlines()[-1] if output else "no findings"
    return Check("publication audit", True, summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight public-release readiness checks.")
    parser.add_argument(
        "--include-ignored",
        action="store_true",
        help="also pass --include-ignored to the publication-safety audit",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    checks = [
        check_required_files(),
        check_python_syntax(),
        check_unit_tests(),
        check_markdown_links(),
        check_large_testdata_lfs(),
        check_source_sidecars(),
        check_run_provenance(),
        check_publication_audit(args.include_ignored),
    ]

    failed = False
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
        failed = failed or not check.ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
