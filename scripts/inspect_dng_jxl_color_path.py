from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JXLINFO = ROOT / "work/jxl-tools/bin/jxlinfo.exe"
JPEG_XL_COMPRESSION = 52546


def add_local_optional_deps() -> None:
    candidates = []
    env_path = os.environ.get("JXL_PYDEPS")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(ROOT / ".deps" / "jxl_pydeps")
    for path in reversed(candidates):
        if optional_deps_usable(path):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)


def optional_deps_usable(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "tifffile" / "__init__.py").is_file()
        and (path / "imagecodecs" / "__init__.py").is_file()
    )


def import_tifffile():
    add_local_optional_deps()
    try:
        import tifffile  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "This script needs tifffile and imagecodecs with DNG/JPEG XL support. "
            "Install the optional dependencies or set JXL_PYDEPS to a directory "
            "containing tifffile and imagecodecs. A repository-local "
            ".deps/jxl_pydeps directory is also detected automatically."
        ) from exc
    if not hasattr(tifffile, "TiffFile"):
        raise SystemExit(
            "Imported tifffile, but it does not expose TiffFile. Set JXL_PYDEPS "
            "to a complete optional dependency directory containing tifffile and "
            "imagecodecs."
        )
    return tifffile


def find_jxlinfo(explicit: Path | None) -> str:
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit(f"jxlinfo does not exist: {explicit}")
        return str(explicit)
    if DEFAULT_JXLINFO.is_file():
        return str(DEFAULT_JXLINFO)
    discovered = shutil.which("jxlinfo")
    if discovered:
        return discovered
    raise SystemExit("jxlinfo was not found; pass --jxlinfo PATH")


def iter_pages(tif) -> Iterator[tuple[str, object]]:
    queue = [(f"IFD {index}", page) for index, page in enumerate(tif.pages)]
    seen_offsets: set[int] = set()
    while queue:
        label, page = queue.pop(0)
        offset = int(page.offset)
        if offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        yield label, page
        subifds = page.pages
        if subifds is not None:
            queue.extend(
                (f"{label}/SubIFD {index}", subifd)
                for index, subifd in enumerate(subifds)
            )


def tag_value(page, name: str, default: object = "unknown") -> object:
    tag = page.tags.get(name)
    return tag.value if tag is not None else default


def classify_jxlinfo(output: str) -> tuple[str, str]:
    header = next(
        (
            line.strip()
            for line in output.splitlines()
            if line.startswith(("JPEG XL image,", "JPEG XL animation,"))
        ),
        "",
    )
    if "(possibly) lossless" in header:
        return "original-profile/non-XYB", header
    if ", lossy," in header:
        return "XYB", header
    return "unknown", header


def inspect_page(
    dng: Path,
    label: str,
    page,
    segment_index: int,
    jxlinfo: str,
) -> bool:
    offsets = tuple(int(value) for value in page.dataoffsets)
    bytecounts = tuple(int(value) for value in page.databytecounts)
    if not offsets or len(offsets) != len(bytecounts):
        raise RuntimeError(f"{label}: missing or inconsistent segment offsets")
    if segment_index >= len(offsets):
        print(label)
        print(
            f"  Segment index {segment_index} is unavailable "
            f"(valid range: 0..{len(offsets) - 1}); skipped."
        )
        return False

    offset = offsets[segment_index]
    bytecount = bytecounts[segment_index]
    with dng.open("rb") as source:
        source.seek(offset)
        segment = source.read(bytecount)
    if len(segment) != bytecount:
        raise RuntimeError(
            f"{label}: expected {bytecount} segment bytes, read {len(segment)}"
        )

    with tempfile.TemporaryDirectory(prefix="dng-jxl-header-") as temp_dir:
        segment_path = Path(temp_dir) / "segment.jxl"
        segment_path.write_bytes(segment)
        result = subprocess.run(
            [jxlinfo, "-v", str(segment_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(
            f"{label}: jxlinfo failed with status {result.returncode}:\n"
            f"{result.stdout.strip()}"
        )

    color_path, header = classify_jxlinfo(result.stdout)
    color_line = next(
        (
            line.strip()
            for line in result.stdout.splitlines()
            if line.startswith("Color space:")
        ),
        "Color space: not reported",
    )
    segment_kind = "tile" if page.is_tiled else "strip"
    print(label)
    print(
        "  DNG tags: "
        f"PhotometricInterpretation={tag_value(page, 'PhotometricInterpretation')}, "
        f"BitsPerSample={tag_value(page, 'BitsPerSample')}"
    )
    print(
        f"  Segment: kind={segment_kind}, index={segment_index}, count={len(offsets)}, "
        f"offset={offset}, bytes={bytecount}"
    )
    print(f"  JXL header: {header or 'not reported'}")
    print(f"  {color_line}")
    print(f"  Inferred color path: {color_path}")
    return True


def inspect_dng(dng: Path, segment_index: int, jxlinfo: str) -> int:
    tifffile = import_tifffile()
    compressed_ifds = 0
    inspected = 0
    print(f"DNG: {dng}")
    with tifffile.TiffFile(dng) as tif:
        for label, page in iter_pages(tif):
            compression = tag_value(page, "Compression", None)
            if compression is None or int(compression) != JPEG_XL_COMPRESSION:
                continue
            compressed_ifds += 1
            if inspect_page(dng, label, page, segment_index, jxlinfo):
                inspected += 1
    if not compressed_ifds:
        print("  No IFD using JPEG XL compression (52546) was found.")
    elif not inspected:
        print(f"  No JXL IFD has segment index {segment_index}.")
    return inspected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one embedded JPEG XL segment per DNG IFD and infer whether "
            "the codestream uses XYB or the original-profile color path."
        )
    )
    parser.add_argument("dngs", nargs="+", type=Path, help="DNG file(s) to inspect")
    parser.add_argument(
        "--segment-index",
        type=int,
        default=0,
        help="tile or strip index to inspect in each JPEG XL IFD (default: 0)",
    )
    parser.add_argument("--jxlinfo", type=Path, help="path to jxlinfo")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.segment_index < 0:
        raise SystemExit("--segment-index must be zero or greater")
    jxlinfo = find_jxlinfo(args.jxlinfo)
    total = 0
    for dng in args.dngs:
        if not dng.is_file():
            raise SystemExit(f"DNG does not exist: {dng}")
        total += inspect_dng(dng, args.segment_index, jxlinfo)
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
