from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GIT_SAFE_DIRECTORY = ROOT.as_posix()
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
    (
        "metadata_identity_field",
        re.compile(
            r'''(?:
                ["'](?:serial(?:number)?|bodyserial|internalserialnumber|ownername|artist)["']\s*:
                |
                \b(?:serial\s+number|body\s+serial\s+number|internal\s+serial\s+number|owner\s+name|artist)\b\s*:
            )''',
            re.IGNORECASE | re.VERBOSE,
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


def lfs_tracked_files(paths: list[Path]) -> set[Path]:
    relative_paths = [rel(path) for path in paths]
    if not relative_paths:
        return set()
    try:
        cp = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={GIT_SAFE_DIRECTORY}",
                "check-attr",
                "-z",
                "--stdin",
                "filter",
            ],
            cwd=ROOT,
            input=b"".join(path.as_posix().encode("utf-8") + b"\0" for path in relative_paths),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()

    tracked: set[Path] = set()
    fields = cp.stdout.split(b"\0")
    for index in range(0, len(fields) - 2, 3):
        path, attribute, value = fields[index : index + 3]
        if attribute == b"filter" and value == b"lfs":
            tracked.add(Path(path.decode("utf-8")))
    return tracked


def scan_file(path: Path, lfs_paths: set[Path]) -> list[Finding]:
    findings: list[Finding] = []
    relative = rel(path)
    suffix = path.suffix.lower()
    size = path.stat().st_size

    lfs_tracked = relative in lfs_paths

    if size > BLOCK_SIZE and lfs_tracked:
        findings.append(
            Finding(
                "info",
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
                "info",
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
            ["git", "-c", f"safe.directory={GIT_SAFE_DIRECTORY}", "ls-files", "--others", "--cached", "--exclude-standard"],
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
    lfs_paths = lfs_tracked_files(files)
    findings: list[Finding] = []
    for path in files:
        findings.extend(scan_file(path, lfs_paths))

    publishable = set(git_unignored_files())
    for path in publishable:
        if path.exists() and path.is_file():
            relative = rel(path)
            if path.suffix.lower() in RISKY_SUFFIXES and not is_safe_binary_location(path):
                findings.append(Finding("block", relative, "currently visible to Git and has risky suffix"))

    severity_rank = {"block": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), str(f.path), f.message))

    if not findings:
        print("No publication-safety findings.")
        return 0

    for finding in findings:
        print(f"[{finding.severity.upper()}] {finding.path}: {finding.message}")

    block_count = sum(1 for finding in findings if finding.severity == "block")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    info_count = sum(1 for finding in findings if finding.severity == "info")
    print(
        f"\nSummary: {block_count} blocking finding(s), "
        f"{warn_count} warning(s), {info_count} informational finding(s)."
    )
    return 1 if block_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
