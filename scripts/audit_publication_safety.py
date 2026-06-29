from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WARN_SIZE = 50 * 1024 * 1024
BLOCK_SIZE = 100 * 1024 * 1024
RISKY_SUFFIXES = {
    ".arw",
    ".dng",
    ".tif",
    ".tiff",
    ".xmp",
    ".raf",
    ".nef",
    ".cr2",
    ".cr3",
    ".rw2",
    ".orf",
    ".jxl",
}
SAFE_BINARY_PREFIXES = {
    Path("testdata"),
}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "work",
    "outputs",
    "input",
    "results",
    "jxl_test_out",
}
TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".ps1",
    ".pp3",
    ".gitignore",
}
SECRET_PATTERNS = [
    ("absolute_windows_path", re.compile(r"[A-Za-z]:\\(?:Users|a\\GitHub|tmp|Windows)\\", re.IGNORECASE)),
    ("user_home", re.compile(r"Users\\[^\\\s]+", re.IGNORECASE)),
    ("sony_dsc_private_name", re.compile(r"_DSC\d{4}", re.IGNORECASE)),
    (
        "metadata_identity_field",
        re.compile(
            r"\b(serial|serialnumber|bodyserial|ownername|artist)\b\s*[:=]",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class Finding:
    severity: str
    path: Path
    message: str


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def rel(path: Path) -> Path:
    return path.relative_to(ROOT)


def iter_files(include_ignored: bool) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        current = Path(dirpath)
        relative_parts = set(current.relative_to(ROOT).parts) if current != ROOT else set()
        if not include_ignored:
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            if relative_parts & IGNORED_DIRS:
                continue
        for filename in filenames:
            files.append(current / filename)
    return files


def is_safe_binary_location(path: Path) -> bool:
    relative = rel(path)
    return any(is_relative_to(relative, prefix) for prefix in SAFE_BINARY_PREFIXES)


def scan_text(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    suffix = path.suffix.lower() or path.name.lower()
    if suffix not in TEXT_SUFFIXES:
        return findings
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    for label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                Finding("warn", rel(path), f"{label} near line {line}: {match.group(0)!r}")
            )
    return findings


def is_lfs_tracked(path: Path) -> bool:
    try:
        cp = subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "check-attr", "filter", "--", str(rel(path))],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return cp.stdout.strip().endswith("filter: lfs")


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    relative = rel(path)
    suffix = path.suffix.lower()
    size = path.stat().st_size

    lfs_tracked = is_lfs_tracked(path)

    if size > BLOCK_SIZE and lfs_tracked:
        findings.append(
            Finding(
                "warn",
                relative,
                f"{size / 1024 / 1024:.1f} MiB requires Git LFS; .gitattributes marks it as LFS",
            )
        )
    elif size > BLOCK_SIZE:
        findings.append(
            Finding("block", relative, f"{size / 1024 / 1024:.1f} MiB exceeds GitHub regular Git hard limit")
        )
    elif size > WARN_SIZE and lfs_tracked:
        findings.append(
            Finding(
                "warn",
                relative,
                f"{size / 1024 / 1024:.1f} MiB is large and will use Git LFS",
            )
        )
    elif size > WARN_SIZE:
        findings.append(
            Finding("warn", relative, f"{size / 1024 / 1024:.1f} MiB is large for normal Git")
        )

    if suffix in RISKY_SUFFIXES and not is_safe_binary_location(path):
        findings.append(Finding("block", relative, f"risky private/archive suffix {suffix} outside testdata/"))

    findings.extend(scan_text(path))
    return findings


def git_unignored_files() -> list[Path]:
    try:
        cp = subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "ls-files", "--others", "--cached", "--exclude-standard"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ROOT / line.strip() for line in cp.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repo for public-release risks.")
    parser.add_argument(
        "--include-ignored",
        action="store_true",
        help="also scan ignored local data directories such as input/ and outputs/",
    )
    args = parser.parse_args()

    files = iter_files(include_ignored=args.include_ignored)
    findings: list[Finding] = []
    for path in files:
        findings.extend(scan_file(path))

    publishable = set(git_unignored_files())
    for path in publishable:
        if path.exists() and path.is_file():
            relative = rel(path)
            if path.suffix.lower() in RISKY_SUFFIXES and not is_safe_binary_location(path):
                findings.append(Finding("block", relative, "currently visible to Git and has risky suffix"))

    severity_rank = {"block": 0, "warn": 1}
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), str(f.path), f.message))

    if not findings:
        print("No publication-safety findings.")
        return 0

    for finding in findings:
        print(f"[{finding.severity.upper()}] {finding.path}: {finding.message}")

    block_count = sum(1 for finding in findings if finding.severity == "block")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    print(f"\nSummary: {block_count} blocking finding(s), {warn_count} warning(s).")
    return 1 if block_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
