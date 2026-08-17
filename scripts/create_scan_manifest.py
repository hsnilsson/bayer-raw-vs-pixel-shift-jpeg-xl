from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

FRAME_RE = re.compile(r"^(?P<prefix>_?DSC)(?P<number>\d{4,6})$", re.IGNORECASE)
RANGE_RE = re.compile(
    r"^(?P<prefix>_?DSC)(?P<start>\d{4,6})-(?P=prefix)(?P<end>\d{4,6})$",
    re.IGNORECASE,
)

ADC_LEVELS = {"lossless", "d003", "d005", "d010"}


@dataclass(frozen=True)
class ParsedStem:
    kind: str
    stem: str
    start: int | None = None
    end: int | None = None
    count: int | None = None


@dataclass
class FileEntry:
    path: str
    name: str
    extension: str
    bytes: int
    mib: float
    role: str
    preservation_class: str
    archive_action: str
    regeneration: str
    privacy: str
    git_policy: str
    sha256: str | None = None


@dataclass
class SequenceEntry:
    stem: str
    mode: str
    frame_count: int
    dng: str
    raw_files_present: int
    raw_files_expected: int
    missing_raw_files: list[str]
    adc_levels_present: list[str]
    dng_mib: float
    adc_mib_by_level: dict[str, float]


@dataclass
class CaptureSet:
    set_id: str
    single_raw: str | None
    single_jpeg: str | None
    pixelshift4_dng: str | None
    pixelshift16_dng: str | None
    adc_levels_for_pixelshift16: list[str]
    notes: str


def parse_stem(stem: str) -> ParsedStem:
    range_match = RANGE_RE.match(stem)
    if range_match:
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        if end >= start:
            return ParsedStem("range", stem, start, end, end - start + 1)
    frame_match = FRAME_RE.match(stem)
    if frame_match:
        number = int(frame_match.group("number"))
        return ParsedStem("single", stem, number, number, 1)
    return ParsedStem("unknown", stem)


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mode_for_sequence(count: int | None) -> str:
    if count == 4:
        return "pixelshift4"
    if count == 16:
        return "pixelshift16"
    if count and count > 1:
        return f"sequence{count}"
    return "dng"


def classify_file(path: Path, scan_root: Path, privacy: str) -> FileEntry:
    relative_parts = path.resolve().relative_to(scan_root.resolve()).parts
    name = path.name
    suffix = path.suffix.lower()
    parsed = parse_stem(path.stem)
    role = "unknown"
    preservation_class = "unknown"
    archive_action = "review"
    regeneration = "unknown"
    git_policy = "do_not_commit"

    if relative_parts and relative_parts[0].lower() == "adc_jxl_dng" and suffix == ".dng":
        role = "adc_dng_jxl_candidate"
        preservation_class = "derived"
        archive_action = "regenerate"
        regeneration = "from_pixelshift_dng_and_adobe_dng_converter"
    elif len(relative_parts) == 1 and suffix == ".arw":
        role = "camera_raw_original"
        preservation_class = "original"
        archive_action = "keep"
        regeneration = "not_regeneratable"
    elif len(relative_parts) == 1 and suffix in {".jpg", ".jpeg"}:
        role = "camera_jpeg_preview"
        preservation_class = "preview"
        archive_action = "review"
        regeneration = "optional_preview"
    elif len(relative_parts) == 1 and suffix == ".dng" and parsed.kind == "range":
        mode = mode_for_sequence(parsed.count)
        role = f"pixelshift2dng_{mode}_master"
        preservation_class = "master"
        archive_action = "keep" if mode == "pixelshift16" else "review"
        regeneration = "from_raw_sequence_if_complete"
    elif len(relative_parts) == 1 and suffix == ".dng":
        role = "dng_master_or_source"
        preservation_class = "master"
        archive_action = "review"
        regeneration = "unknown"
    elif suffix in {".json", ".md", ".csv", ".txt", ".xmp"}:
        role = "metadata_or_sidecar"
        preservation_class = "metadata"
        archive_action = "keep"
        regeneration = "manual_or_regenerated_metadata"
        git_policy = "review_before_commit"

    return FileEntry(
        path=relpath(path, scan_root),
        name=name,
        extension=suffix.lstrip("."),
        bytes=path.stat().st_size,
        mib=round(path.stat().st_size / 1024 / 1024, 3),
        role=role,
        preservation_class=preservation_class,
        archive_action=archive_action,
        regeneration=regeneration,
        privacy=privacy,
        git_policy=git_policy,
    )


def root_files(scan_root: Path, suffix: str) -> dict[int, Path]:
    files: dict[int, Path] = {}
    for path in scan_root.glob(f"*{suffix}"):
        parsed = parse_stem(path.stem)
        if parsed.kind == "single" and parsed.start is not None:
            files[parsed.start] = path
    return files


def adc_candidates(scan_root: Path) -> dict[str, dict[str, Path]]:
    candidates: dict[str, dict[str, Path]] = defaultdict(dict)
    adc_root = scan_root / "adc_jxl_dng"
    if not adc_root.is_dir():
        return candidates
    for level_dir in sorted(path for path in adc_root.iterdir() if path.is_dir()):
        level = level_dir.name
        for path in sorted(level_dir.glob("*.dng")):
            candidates[path.stem][level] = path
    return candidates


def build_sequences(scan_root: Path, entries_by_path: dict[str, FileEntry]) -> list[SequenceEntry]:
    raw_by_number = root_files(scan_root, ".ARW") | root_files(scan_root, ".arw")
    adc_by_stem = adc_candidates(scan_root)
    sequences: list[SequenceEntry] = []
    for dng in sorted(scan_root.glob("*.dng")):
        parsed = parse_stem(dng.stem)
        if parsed.kind != "range" or parsed.start is None or parsed.end is None:
            continue
        expected_numbers = list(range(parsed.start, parsed.end + 1))
        missing = [f"_DSC{number:04d}.ARW" for number in expected_numbers if number not in raw_by_number]
        adc_levels = sorted(adc_by_stem.get(dng.stem, {}))
        sequences.append(
            SequenceEntry(
                stem=dng.stem,
                mode=mode_for_sequence(parsed.count),
                frame_count=int(parsed.count or 0),
                dng=relpath(dng, scan_root),
                raw_files_present=len(expected_numbers) - len(missing),
                raw_files_expected=len(expected_numbers),
                missing_raw_files=missing,
                adc_levels_present=adc_levels,
                dng_mib=round(dng.stat().st_size / 1024 / 1024, 3),
                adc_mib_by_level={
                    level: round(path.stat().st_size / 1024 / 1024, 3)
                    for level, path in sorted(adc_by_stem.get(dng.stem, {}).items())
                },
            )
        )
        entry = entries_by_path.get(relpath(dng, scan_root))
        if entry is not None and missing:
            entry.archive_action = "review"
            entry.regeneration = "raw_sequence_incomplete"
    return sequences


def build_capture_sets(scan_root: Path, sequences: list[SequenceEntry]) -> list[CaptureSet]:
    raw_by_number = root_files(scan_root, ".ARW") | root_files(scan_root, ".arw")
    jpg_by_number = root_files(scan_root, ".JPG") | root_files(scan_root, ".jpg")
    sequence_by_start: dict[int, SequenceEntry] = {}
    sequence_numbers: set[int] = set()
    for sequence in sequences:
        parsed = parse_stem(sequence.stem)
        if parsed.start is None or parsed.end is None:
            continue
        sequence_by_start[parsed.start] = sequence
        sequence_numbers.update(range(parsed.start, parsed.end + 1))

    capture_sets: list[CaptureSet] = []
    assigned_sequences: set[str] = set()
    singles = sorted(number for number in raw_by_number if number not in sequence_numbers)
    for number in singles:
        ps4 = sequence_by_start.get(number + 1)
        ps16_start = None
        if ps4 and ps4.mode == "pixelshift4":
            parsed_ps4 = parse_stem(ps4.stem)
            ps16_start = (parsed_ps4.end or number) + 1
        else:
            ps16_start = number + 1
        ps16 = sequence_by_start.get(ps16_start)
        if ps16 and ps16.mode != "pixelshift16":
            ps16 = None
        if ps4 and ps4.mode != "pixelshift4":
            ps4 = None

        if ps4:
            assigned_sequences.add(ps4.stem)
        if ps16:
            assigned_sequences.add(ps16.stem)
        capture_sets.append(
            CaptureSet(
                set_id=f"_DSC{number:04d}",
                single_raw=relpath(raw_by_number[number], scan_root),
                single_jpeg=relpath(jpg_by_number[number], scan_root) if number in jpg_by_number else None,
                pixelshift4_dng=ps4.dng if ps4 else None,
                pixelshift16_dng=ps16.dng if ps16 else None,
                adc_levels_for_pixelshift16=ps16.adc_levels_present if ps16 else [],
                notes="inferred from filename order",
            )
        )

    for sequence in sequences:
        if sequence.stem in assigned_sequences:
            continue
        capture_sets.append(
            CaptureSet(
                set_id=sequence.stem,
                single_raw=None,
                single_jpeg=None,
                pixelshift4_dng=sequence.dng if sequence.mode == "pixelshift4" else None,
                pixelshift16_dng=sequence.dng if sequence.mode == "pixelshift16" else None,
                adc_levels_for_pixelshift16=sequence.adc_levels_present if sequence.mode == "pixelshift16" else [],
                notes="sequence without inferred single-shot partner",
            )
        )
    return capture_sets


def summarize_entries(entries: list[FileEntry]) -> dict[str, Any]:
    total_bytes = sum(entry.bytes for entry in entries)
    return {
        "files": len(entries),
        "bytes": total_bytes,
        "gib": round(total_bytes / 1024 / 1024 / 1024, 3),
        "by_role": dict(Counter(entry.role for entry in entries)),
        "by_preservation_class": dict(Counter(entry.preservation_class for entry in entries)),
        "by_archive_action": dict(Counter(entry.archive_action for entry in entries)),
        "bytes_by_archive_action": {
            action: sum(entry.bytes for entry in entries if entry.archive_action == action)
            for action in sorted({entry.archive_action for entry in entries})
        },
    }


def build_recommendations(entries: list[FileEntry]) -> dict[str, Any]:
    regenerate = [entry.path for entry in entries if entry.archive_action == "regenerate"]
    keep = [entry.path for entry in entries if entry.archive_action == "keep"]
    review = [entry.path for entry in entries if entry.archive_action == "review"]
    return {
        "keep": keep,
        "safe_to_regenerate": regenerate,
        "review_before_delete": review,
        "notes": [
            "This manifest does not delete or move files.",
            "Files marked safe_to_regenerate should only be deleted after the source master, tool version, and command are recorded.",
            "Camera raw originals are marked keep because they cannot be recreated.",
            "PixelShift2DNG masters may be regeneratable from complete raw sequences, but they are still treated as important masters.",
        ],
    }


def build_manifest(
    scan_root: Path,
    *,
    privacy: str = "private",
    hash_files: bool = False,
    film_stock: str | None = None,
    film_type: str | None = None,
    include_absolute_paths: bool = False,
    exclude_paths: set[Path] | None = None,
) -> dict[str, Any]:
    scan_root = scan_root.resolve()
    if not scan_root.is_dir():
        raise FileNotFoundError(f"scan root does not exist: {scan_root}")

    excluded = {path.resolve() for path in (exclude_paths or set())}
    files = sorted(
        path
        for path in scan_root.rglob("*")
        if path.is_file() and path.resolve() not in excluded
    )
    entries = [classify_file(path, scan_root, privacy) for path in files]
    entries_by_path = {entry.path: entry for entry in entries}
    if hash_files:
        for entry in entries:
            entry.sha256 = sha256_file(scan_root / entry.path)

    sequences = build_sequences(scan_root, entries_by_path)
    capture_sets = build_capture_sets(scan_root, sequences)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan_root_name": scan_root.name,
        "scan_root": str(scan_root) if include_absolute_paths else None,
        "film_stock": film_stock,
        "film_type": film_type,
        "privacy_default": privacy,
        "hashes": "sha256" if hash_files else "not_computed",
        "totals": summarize_entries(entries),
        "capture_sets": [asdict(item) for item in capture_sets],
        "sequences": [asdict(item) for item in sequences],
        "files": [asdict(entry) for entry in entries],
        "recommendations": build_recommendations(entries),
    }
    return manifest


def json_write(path: Path, data: Any, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def fmt_gib(bytes_value: int) -> str:
    return f"{bytes_value / 1024 / 1024 / 1024:.2f} GiB"


def markdown_for_manifest(manifest: dict[str, Any]) -> str:
    totals = manifest["totals"]
    lines = [
        f"# Scan Manifest: {manifest['scan_root_name']}",
        "",
        "This sidecar is generated metadata for archive triage. It does not imply",
        "that files are safe to delete without human review.",
        "",
        "## Summary",
        "",
        f"- Files: `{totals['files']}`",
        f"- Total size: `{totals['gib']:.2f} GiB`",
        f"- Privacy default: `{manifest['privacy_default']}`",
        f"- Hashes: `{manifest['hashes']}`",
    ]
    if manifest.get("film_stock"):
        lines.append(f"- Film stock: `{manifest['film_stock']}`")
    if manifest.get("film_type"):
        lines.append(f"- Film type: `{manifest['film_type']}`")

    lines.extend(["", "## Storage By Action", ""])
    lines.append("| Action | Files | Size | Meaning |")
    lines.append("| --- | ---: | ---: | --- |")
    meanings = {
        "keep": "originals, masters, or metadata worth retaining",
        "review": "possibly useful, but needs human decision",
        "regenerate": "derived output that should be reproducible from retained masters",
    }
    counts = totals["by_archive_action"]
    bytes_by_action = totals["bytes_by_archive_action"]
    for action in sorted(counts):
        lines.append(
            f"| `{action}` | {counts[action]} | {fmt_gib(bytes_by_action[action])} | "
            f"{meanings.get(action, 'unclassified')} |"
        )

    lines.extend(["", "## Capture Sets", ""])
    lines.append("| Set | Single | PS4 DNG | PS16 DNG | ADC levels | Notes |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in manifest["capture_sets"]:
        lines.append(
            f"| `{item['set_id']}` | "
            f"{md_path(item['single_raw'])} | "
            f"{md_path(item['pixelshift4_dng'])} | "
            f"{md_path(item['pixelshift16_dng'])} | "
            f"`{', '.join(item['adc_levels_for_pixelshift16']) or '-'}` | "
            f"{item['notes']} |"
        )

    lines.extend(["", "## PixelShift Sequences", ""])
    lines.append("| DNG | Mode | Raw files | Missing raw files | ADC levels | DNG size |")
    lines.append("| --- | --- | ---: | --- | --- | ---: |")
    for item in manifest["sequences"]:
        missing = ", ".join(item["missing_raw_files"]) if item["missing_raw_files"] else "-"
        lines.append(
            f"| {md_path(item['dng'])} | `{item['mode']}` | "
            f"{item['raw_files_present']}/{item['raw_files_expected']} | "
            f"{missing} | `{', '.join(item['adc_levels_present']) or '-'}` | "
            f"{item['dng_mib']:.1f} MiB |"
        )

    recommendations = manifest["recommendations"]
    lines.extend(["", "## Recommendations", ""])
    for note in recommendations["notes"]:
        lines.append(f"- {note}")

    safe_count = len(recommendations["safe_to_regenerate"])
    safe_bytes = sum(
        entry["bytes"]
        for entry in manifest["files"]
        if entry["path"] in set(recommendations["safe_to_regenerate"])
    )
    lines.extend(
        [
            "",
            f"`safe_to_regenerate`: {safe_count} files, {fmt_gib(safe_bytes)}.",
            "",
            "Review the JSON manifest for the full file list and SHA-256 hashes when",
            "generated with `--hash`.",
            "",
        ]
    )
    return "\n".join(lines)


def md_path(path: str | None) -> str:
    if not path:
        return "-"
    return f"`{path}`"


def write_outputs(manifest: dict[str, Any], out_json: Path, out_md: Path, force: bool) -> None:
    if out_json.exists() and not force:
        raise FileExistsError(f"{out_json} already exists; pass --force to overwrite")
    if out_md.exists() and not force:
        raise FileExistsError(f"{out_md} already exists; pass --force to overwrite")
    json_write(out_json, manifest, force)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(markdown_for_manifest(manifest), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create JSON and Markdown sidecars for a private camera-scan folder."
    )
    parser.add_argument("scan_root", type=Path)
    parser.add_argument("--out-json", type=Path, help="default: <scan_root>/scan_manifest.json")
    parser.add_argument("--out-md", type=Path, help="default: <scan_root>/scan_manifest.md")
    parser.add_argument("--privacy", default="private")
    parser.add_argument("--film-stock")
    parser.add_argument("--film-type")
    parser.add_argument("--hash", action="store_true", help="compute SHA-256 for every file")
    parser.add_argument("--force", action="store_true", help="overwrite existing manifest files")
    parser.add_argument("--include-absolute-paths", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print summary without writing files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scan_root = args.scan_root.resolve()
    out_json = args.out_json or scan_root / "scan_manifest.json"
    out_md = args.out_md or scan_root / "scan_manifest.md"
    manifest = build_manifest(
        scan_root,
        privacy=args.privacy,
        hash_files=args.hash,
        film_stock=args.film_stock,
        film_type=args.film_type,
        include_absolute_paths=args.include_absolute_paths,
        exclude_paths={out_json, out_md},
    )
    if args.dry_run:
        print(markdown_for_manifest(manifest))
        return 0

    write_outputs(manifest, out_json, out_md, args.force)
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
