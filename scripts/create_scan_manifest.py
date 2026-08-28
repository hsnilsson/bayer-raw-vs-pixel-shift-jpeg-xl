from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
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
PIXELSHIFT_INFO_RE = re.compile(
    r"Group\s+(?P<group>\d+),\s*Shot\s+(?P<shot>\d+)/(?P<total>\d+)",
    re.IGNORECASE,
)

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
class RawPixelShiftFrame:
    path: str
    number: int | None
    group_id: str
    shot: int
    expected_shots: int
    release_mode: str | None


@dataclass
class RawPixelShiftGroup:
    group_id: str
    mode: str
    raw_files_present: int
    raw_files_expected: int
    raw_files: list[str]
    missing_shots: list[int]
    first_raw: str | None
    last_raw: str | None
    first_frame_number: int | None
    last_frame_number: int | None
    notes: str


@dataclass
class CaptureSet:
    set_id: str
    single_raw: str | None
    single_jpeg: str | None
    pixelshift4_dng: str | None
    pixelshift16_dng: str | None
    adc_levels_for_pixelshift16: list[str]
    notes: str
    pixelshift4_raw_group: str | None = None
    pixelshift16_raw_group: str | None = None
    single_raw_kind: str = "unknown"
    storage_budget_role: str = "review"


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


def mode_for_raw_pixelshift(count: int | None) -> str:
    if count == 1:
        return "pixelshift1"
    return mode_for_sequence(count)


def parse_pixelshift_info(value: object) -> tuple[str, int, int] | None:
    if not value:
        return None
    match = PIXELSHIFT_INFO_RE.search(str(value))
    if not match:
        return None
    return (
        match.group("group"),
        int(match.group("shot")),
        int(match.group("total")),
    )


def frame_number_from_name(name: str) -> int | None:
    parsed = parse_stem(Path(name).stem)
    return parsed.start if parsed.kind == "single" else None


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
    elif suffix == ".arw":
        role = "camera_raw_original"
        preservation_class = "original"
        archive_action = "keep"
        regeneration = "not_regeneratable"
    elif suffix in {".jpg", ".jpeg"}:
        role = "camera_jpeg_preview"
        preservation_class = "preview"
        archive_action = "review"
        regeneration = "optional_preview"
    elif suffix == ".dng" and parsed.kind == "range":
        mode = mode_for_sequence(parsed.count)
        role = f"pixelshift2dng_{mode}_master"
        preservation_class = "master"
        archive_action = "keep" if mode == "pixelshift16" else "review"
        regeneration = "from_raw_sequence_if_complete"
    elif suffix == ".dng":
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


def scan_source_files(scan_root: Path, suffixes: set[str]) -> list[Path]:
    files = []
    for path in scan_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        relative_parts = path.resolve().relative_to(scan_root.resolve()).parts
        if relative_parts and relative_parts[0].lower() in {"adc_jxl_dng", "_review"}:
            continue
        files.append(path)
    return sorted(files)


def root_files(scan_root: Path, suffix: str) -> dict[int, Path]:
    files: dict[int, Path] = {}
    for path in scan_source_files(scan_root, {suffix.lower()}):
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


def exiftool_command(explicit: str | None = None) -> str | None:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(
        [
            r"C:\Program Files\ExifTool\ExifTool.exe",
            r"C:\Program Files (x86)\ExifTool\ExifTool.exe",
            "exiftool.exe",
            "exiftool",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
        found = shutil.which(candidate)
        if found:
            return found
    return None


def relpath_from_exif_row(row: dict[str, Any], scan_root: Path) -> str:
    source = str(row.get("SourceFile") or "")
    file_name = str(row.get("FileName") or Path(source).name)
    source_path = Path(source) if source else scan_root / file_name
    try:
        return source_path.resolve().relative_to(scan_root.resolve()).as_posix()
    except ValueError:
        return file_name


def raw_pixelshift_groups_from_rows(
    rows: list[dict[str, Any]],
    scan_root: Path,
) -> list[RawPixelShiftGroup]:
    frames_by_group: dict[str, list[RawPixelShiftFrame]] = defaultdict(list)
    for row in rows:
        parsed_info = parse_pixelshift_info(row.get("PixelShiftInfo"))
        if not parsed_info:
            continue
        group_id, shot, expected_shots = parsed_info
        path = relpath_from_exif_row(row, scan_root)
        frames_by_group[group_id].append(
            RawPixelShiftFrame(
                path=path,
                number=frame_number_from_name(Path(path).name),
                group_id=group_id,
                shot=shot,
                expected_shots=expected_shots,
                release_mode=row.get("ReleaseMode"),
            )
        )

    groups: list[RawPixelShiftGroup] = []
    for group_id, frames in sorted(
        frames_by_group.items(),
        key=lambda item: min(
            (frame.number for frame in item[1] if frame.number is not None),
            default=10**12,
        ),
    ):
        expected = Counter(frame.expected_shots for frame in frames).most_common(1)[0][0]
        frames_by_shot = {frame.shot: frame for frame in frames}
        ordered_frames = sorted(
            frames,
            key=lambda frame: (
                frame.number if frame.number is not None else 10**12,
                frame.shot,
                frame.path,
            ),
        )
        numbers = [frame.number for frame in ordered_frames if frame.number is not None]
        raw_files = [frame.path for frame in ordered_frames]
        missing_shots = [shot for shot in range(1, expected + 1) if shot not in frames_by_shot]
        notes = ["ExifTool PixelShiftInfo"]
        if missing_shots:
            notes.append("missing shots")
        if len({frame.expected_shots for frame in frames}) > 1:
            notes.append("conflicting expected shot counts")
        groups.append(
            RawPixelShiftGroup(
                group_id=group_id,
                mode=mode_for_raw_pixelshift(expected),
                raw_files_present=len(frames),
                raw_files_expected=expected,
                raw_files=raw_files,
                missing_shots=missing_shots,
                first_raw=raw_files[0] if raw_files else None,
                last_raw=raw_files[-1] if raw_files else None,
                first_frame_number=min(numbers) if numbers else None,
                last_frame_number=max(numbers) if numbers else None,
                notes=", ".join(notes),
            )
        )
    return groups


def read_raw_pixelshift_groups(
    scan_root: Path,
    *,
    exiftool: str | None = None,
) -> tuple[list[RawPixelShiftGroup], dict[str, Any]]:
    raw_paths = scan_source_files(scan_root, {".arw"})
    status: dict[str, Any] = {
        "status": "not_run",
        "tool": None,
        "raw_files_checked": len(raw_paths),
        "notes": [],
    }
    if not raw_paths:
        status["status"] = "no_raw_files"
        return [], status

    tool = exiftool_command(exiftool)
    if tool is None:
        status["status"] = "exiftool_not_found"
        status["notes"].append("Install ExifTool or pass --exiftool to detect raw PixelShift groups.")
        return [], status

    command = [
        tool,
        "-json",
        "-FileName",
        "-PixelShiftInfo",
        "-SequenceNumber",
        "-ReleaseMode",
        *[str(path) for path in raw_paths],
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    status["tool"] = tool
    if completed.returncode != 0:
        status["status"] = "exiftool_failed"
        status["notes"].append(completed.stderr.strip())
        return [], status

    rows = json.loads(completed.stdout or "[]")
    groups = raw_pixelshift_groups_from_rows(rows, scan_root)
    status["status"] = "ok"
    status["groups_detected"] = len(groups)
    return groups, status


def build_sequences(scan_root: Path, entries_by_path: dict[str, FileEntry]) -> list[SequenceEntry]:
    raw_by_number = root_files(scan_root, ".ARW") | root_files(scan_root, ".arw")
    adc_by_stem = adc_candidates(scan_root)
    sequences: list[SequenceEntry] = []
    for dng in scan_source_files(scan_root, {".dng"}):
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


def build_capture_sets_from_dng_sequences(
    scan_root: Path,
    sequences: list[SequenceEntry],
) -> list[CaptureSet]:
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
                single_raw_kind="filename_inferred_single_raw",
                storage_budget_role="primary_candidate",
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
                single_raw_kind="none",
                storage_budget_role="unpaired_secondary",
            )
        )
    return capture_sets


def build_capture_sets_from_raw_groups(
    scan_root: Path,
    raw_groups: list[RawPixelShiftGroup],
) -> list[CaptureSet]:
    raw_by_number = root_files(scan_root, ".ARW") | root_files(scan_root, ".arw")
    jpg_by_number = root_files(scan_root, ".JPG") | root_files(scan_root, ".jpg")
    raw_group_by_start = {
        group.first_frame_number: group
        for group in raw_groups
        if group.first_frame_number is not None
    }
    sequence_numbers: set[int] = set()
    for group in raw_groups:
        if group.raw_files_expected <= 1:
            continue
        for raw_file in group.raw_files:
            number = frame_number_from_name(Path(raw_file).name)
            if number is not None:
                sequence_numbers.add(number)

    singles = sorted(number for number in raw_by_number if number not in sequence_numbers)
    capture_sets: list[CaptureSet] = []
    assigned_groups: set[str] = set()
    for number in singles:
        ps4 = raw_group_by_start.get(number + 1)
        if ps4 and ps4.mode != "pixelshift4":
            ps4 = None

        ps16_start = None
        if ps4 and ps4.last_frame_number is not None:
            ps16_start = ps4.last_frame_number + 1
        else:
            ps16_start = number + 1
        ps16 = raw_group_by_start.get(ps16_start)
        if ps16 and ps16.mode != "pixelshift16":
            ps16 = None

        if ps4:
            assigned_groups.add(ps4.group_id)
        if ps16:
            assigned_groups.add(ps16.group_id)
        is_pixelshift1_single = (
            number in raw_group_by_start
            and raw_group_by_start[number].mode == "pixelshift1"
        )
        single_note = "inferred from raw PixelShiftInfo and filename order"
        single_raw_kind = "normal_single_raw"
        storage_budget_role = "primary_candidate"
        if is_pixelshift1_single:
            single_note = (
                "single frame is an ExifTool PixelShiftInfo 1/1 group; "
                "exclude from primary storage-budget comparison"
            )
            single_raw_kind = "pixelshift1_single_raw"
            storage_budget_role = "secondary_only"

        capture_sets.append(
            CaptureSet(
                set_id=f"_DSC{number:04d}",
                single_raw=relpath(raw_by_number[number], scan_root),
                single_jpeg=relpath(jpg_by_number[number], scan_root) if number in jpg_by_number else None,
                pixelshift4_dng=None,
                pixelshift16_dng=None,
                adc_levels_for_pixelshift16=[],
                notes=single_note,
                pixelshift4_raw_group=ps4.group_id if ps4 else None,
                pixelshift16_raw_group=ps16.group_id if ps16 else None,
                single_raw_kind=single_raw_kind,
                storage_budget_role=storage_budget_role,
            )
        )

    for group in raw_groups:
        if group.raw_files_expected <= 1 or group.group_id in assigned_groups:
            continue
        capture_sets.append(
            CaptureSet(
                set_id=f"{group.first_raw or group.group_id}",
                single_raw=None,
                single_jpeg=None,
                pixelshift4_dng=None,
                pixelshift16_dng=None,
                adc_levels_for_pixelshift16=[],
                notes="raw PixelShift group without inferred single-shot partner",
                pixelshift4_raw_group=group.group_id if group.mode == "pixelshift4" else None,
                pixelshift16_raw_group=group.group_id if group.mode == "pixelshift16" else None,
                single_raw_kind="none",
                storage_budget_role="unpaired_secondary",
            )
        )
    return capture_sets


def build_capture_sets(
    scan_root: Path,
    sequences: list[SequenceEntry],
    raw_groups: list[RawPixelShiftGroup],
) -> list[CaptureSet]:
    if sequences:
        return build_capture_sets_from_dng_sequences(scan_root, sequences)
    return build_capture_sets_from_raw_groups(scan_root, raw_groups)


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
    shot_year: str | None = None,
    include_absolute_paths: bool = False,
    exclude_paths: set[Path] | None = None,
    exiftool: str | None = None,
    use_exiftool: bool = True,
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
    if use_exiftool:
        raw_pixelshift_groups, raw_pixelshift_detection = read_raw_pixelshift_groups(
            scan_root,
            exiftool=exiftool,
        )
    else:
        raw_pixelshift_groups = []
        raw_pixelshift_detection = {
            "status": "disabled",
            "tool": None,
            "raw_files_checked": 0,
            "notes": ["Raw PixelShift detection disabled."],
        }
    capture_sets = build_capture_sets(scan_root, sequences, raw_pixelshift_groups)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan_root_name": scan_root.name,
        "scan_root": str(scan_root) if include_absolute_paths else None,
        "film_stock": film_stock,
        "film_type": film_type,
        "shot_year": shot_year,
        "privacy_default": privacy,
        "hashes": "sha256" if hash_files else "not_computed",
        "totals": summarize_entries(entries),
        "capture_sets": [asdict(item) for item in capture_sets],
        "sequences": [asdict(item) for item in sequences],
        "raw_pixelshift_detection": raw_pixelshift_detection,
        "raw_pixelshift_groups": [asdict(item) for item in raw_pixelshift_groups],
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
    if manifest.get("shot_year"):
        lines.append(f"- Shot year: `{manifest['shot_year']}`")

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
    lines.append(
        "| Set | Single | Single kind | Storage role | PS4 DNG | PS4 raw group | "
        "PS16 DNG | PS16 raw group | ADC levels | Notes |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in manifest["capture_sets"]:
        lines.append(
            f"| `{item['set_id']}` | "
            f"{md_path(item['single_raw'])} | "
            f"`{item.get('single_raw_kind', 'unknown')}` | "
            f"`{item.get('storage_budget_role', 'review')}` | "
            f"{md_path(item['pixelshift4_dng'])} | "
            f"{md_path(item.get('pixelshift4_raw_group'))} | "
            f"{md_path(item['pixelshift16_dng'])} | "
            f"{md_path(item.get('pixelshift16_raw_group'))} | "
            f"`{', '.join(item['adc_levels_for_pixelshift16']) or '-'}` | "
            f"{item['notes']} |"
        )

    detection = manifest.get("raw_pixelshift_detection", {})
    lines.extend(["", "## Raw PixelShift Groups", ""])
    lines.append(f"Detection status: `{detection.get('status', 'unknown')}`.")
    if detection.get("tool"):
        lines.append(f"ExifTool: `{detection['tool']}`.")
    if detection.get("notes"):
        for note in detection["notes"]:
            lines.append(f"- {note}")
    lines.extend(["", "| Group | Mode | Raw files | Missing shots | First | Last | Notes |"])
    lines.append("| --- | --- | ---: | --- | --- | --- | --- |")
    for item in manifest.get("raw_pixelshift_groups", []):
        missing = ", ".join(str(shot) for shot in item["missing_shots"]) if item["missing_shots"] else "-"
        lines.append(
            f"| `{item['group_id']}` | `{item['mode']}` | "
            f"{item['raw_files_present']}/{item['raw_files_expected']} | "
            f"{missing} | {md_path(item['first_raw'])} | {md_path(item['last_raw'])} | "
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
    parser.add_argument("--shot-year")
    parser.add_argument("--exiftool", help="ExifTool executable path; default: auto-detect")
    parser.add_argument("--no-exiftool", action="store_true", help="skip ARW PixelShiftInfo detection")
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
        shot_year=args.shot_year,
        include_absolute_paths=args.include_absolute_paths,
        exclude_paths={out_json, out_md},
        exiftool=args.exiftool,
        use_exiftool=not args.no_exiftool,
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
