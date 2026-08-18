from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from run_dng_jxl_verification import dng_metadata, find_main_image, import_tifffile  # noqa: E402


@dataclass
class DuplicatePair:
    canonical: Path
    duplicate: Path


@dataclass
class DuplicateComparison:
    canonical: str
    duplicate: str
    canonical_bytes: int
    duplicate_bytes: int
    same_file_bytes: bool
    same_main_image: bool
    canonical_main_sha256: str
    duplicate_main_sha256: str
    same_key_metadata: bool
    differing_key_metadata: list[str]
    recommendation: str


DUPLICATE_SUFFIX = "-(1)"
KEY_METADATA = [
    "dng_version",
    "dng_backward_version",
    "shape",
    "active_crop_origin",
    "active_crop_size",
    "compression",
    "photometric",
    "bits_per_sample",
    "white_level",
    "is_tiled",
    "tile_width",
    "tile_length",
    "segments",
]


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_stem_for_duplicate(stem: str) -> str | None:
    if not stem.endswith(DUPLICATE_SUFFIX):
        return None
    return stem[: -len(DUPLICATE_SUFFIX)]


def discover_duplicate_pairs(scan_root: Path) -> list[DuplicatePair]:
    candidates = sorted(scan_root.rglob(f"*{DUPLICATE_SUFFIX}.dng"))
    pairs: list[DuplicatePair] = []
    for duplicate in candidates:
        canonical_stem = canonical_stem_for_duplicate(duplicate.stem)
        if canonical_stem is None:
            continue
        canonical = scan_root / f"{canonical_stem}.dng"
        if canonical.is_file():
            pairs.append(DuplicatePair(canonical=canonical, duplicate=duplicate))
    return pairs


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decoded_main_image_sha256(path: Path, maxworkers: int) -> str:
    tifffile = import_tifffile()
    digest = hashlib.sha256()
    with tifffile.TiffFile(path) as tif:
        main = find_main_image(tif)
        page = main.page
        digest.update(json.dumps({"shape": main.shape}, sort_keys=True).encode("utf-8"))
        for data, indices, _shape in page.segments(sort=True, maxworkers=maxworkers):
            tile = np.asarray(data)
            if tile.ndim == 4 and tile.shape[0] == 1:
                tile = tile[0]
            if tile.ndim != 3:
                continue
            if tile.shape[2] > 3:
                tile = tile[:, :, :3]
            tile = np.ascontiguousarray(tile.astype("<u2", copy=False))
            digest.update(json.dumps(tuple(int(value) for value in indices), sort_keys=True).encode("utf-8"))
            digest.update(json.dumps(tuple(int(value) for value in tile.shape), sort_keys=True).encode("utf-8"))
            digest.update(tile.tobytes(order="C"))
    return digest.hexdigest()


def differing_metadata_keys(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return [key for key in KEY_METADATA if left.get(key) != right.get(key)]


def compare_pair(pair: DuplicatePair, scan_root: Path, maxworkers: int) -> DuplicateComparison:
    canonical_file_hash = file_sha256(pair.canonical)
    duplicate_file_hash = file_sha256(pair.duplicate)
    canonical_main_hash = decoded_main_image_sha256(pair.canonical, maxworkers=maxworkers)
    duplicate_main_hash = decoded_main_image_sha256(pair.duplicate, maxworkers=maxworkers)
    canonical_meta = dng_metadata(pair.canonical)
    duplicate_meta = dng_metadata(pair.duplicate)
    differing_keys = differing_metadata_keys(canonical_meta, duplicate_meta)
    same_main = canonical_main_hash == duplicate_main_hash
    same_key_meta = not differing_keys
    recommendation = "delete_duplicate" if same_main and same_key_meta else "keep_for_review"
    return DuplicateComparison(
        canonical=relpath(pair.canonical, scan_root),
        duplicate=relpath(pair.duplicate, scan_root),
        canonical_bytes=pair.canonical.stat().st_size,
        duplicate_bytes=pair.duplicate.stat().st_size,
        same_file_bytes=canonical_file_hash == duplicate_file_hash,
        same_main_image=same_main,
        canonical_main_sha256=canonical_main_hash,
        duplicate_main_sha256=duplicate_main_hash,
        same_key_metadata=same_key_meta,
        differing_key_metadata=differing_keys,
        recommendation=recommendation,
    )


def write_csv(path: Path, rows: list[DuplicateComparison]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(asdict(rows[0]).keys()) if rows else list(DuplicateComparison.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            data = asdict(row)
            data["differing_key_metadata"] = ";".join(row.differing_key_metadata)
            writer.writerow(data)


def write_markdown(path: Path, rows: list[DuplicateComparison]) -> None:
    lines = [
        "# DNG Duplicate Candidate Report",
        "",
        "This compares root DNG files against `-(1)` duplicate candidates by decoded main image data.",
        "",
        "| Canonical | Duplicate | Same file bytes | Same main image | Same key metadata | Recommendation |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.canonical}` | `{row.duplicate}` | "
            f"`{row.same_file_bytes}` | `{row.same_main_image}` | "
            f"`{row.same_key_metadata}` | `{row.recommendation}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare PixelShift2DNG duplicate candidates by decoded main image data."
    )
    parser.add_argument("scan_root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--maxworkers", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scan_root = args.scan_root.resolve()
    out_dir = args.out_dir or scan_root / "_review" / "duplicate_dng_candidates"
    pairs = discover_duplicate_pairs(scan_root)
    if not pairs:
        raise SystemExit(f"no duplicate candidates found under {scan_root}")

    rows = []
    for pair in pairs:
        print(f"Comparing {pair.duplicate.name}", flush=True)
        rows.append(compare_pair(pair, scan_root, args.maxworkers))

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "duplicate_dng_comparison.json"
    csv_path = out_dir / "duplicate_dng_comparison.csv"
    md_path = out_dir / "duplicate_dng_comparison.md"
    json_path.write_text(json.dumps([asdict(row) for row in rows], indent=2) + "\n", encoding="utf-8")
    write_csv(csv_path, rows)
    write_markdown(md_path, rows)
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
