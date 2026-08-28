from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from break_even_image_tools import read_rgb_image  # noqa: E402
import run_local_scan_study as local_study  # noqa: E402


DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_REGISTERED_ROOT = ROOT / "outputs/registered_raw61_to_ps16"
DEFAULT_OUTPUT_DIR = ROOT / "results/break_even_review_contexts"


@dataclass(frozen=True)
class ContextCase:
    scan_set: str
    set_id: str


@dataclass(frozen=True)
class ContextImage:
    source: str
    output: str
    scan_set: str
    set_id: str
    role: str
    crop_name: str
    crop: tuple[int, int, int, int]
    source_width: int
    source_height: int
    output_width: int
    output_height: int


def parse_case(value: str) -> ContextCase:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError('case must be "scan set|set id"')
    return ContextCase(parts[0], parts[1])


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height")
    try:
        x, y, width, height = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop values must be integers") from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("crop values must be non-negative x/y and positive width/height")
    return x, y, width, height


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def to_display(arr: np.ndarray) -> Image.Image:
    values = np.asarray(arr, dtype=np.float32)
    if values.ndim == 2:
        values = np.repeat(values[:, :, None], 3, axis=2)
    if np.issubdtype(arr.dtype, np.integer):
        values = values / float(np.iinfo(arr.dtype).max)
    low, high = np.percentile(values, [0.5, 99.5])
    if high <= low:
        high = low + 1e-6
    values = np.clip((values - low) / (high - low), 0.0, 1.0)
    return Image.fromarray(np.round(values[:, :, :3] * 255).astype(np.uint8), mode="RGB")


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    font = ImageFont.load_default()
    bbox = draw.textbbox(xy, text, font=font)
    padded = (bbox[0] - 5, bbox[1] - 4, bbox[2] + 5, bbox[3] + 4)
    draw.rectangle(padded, fill=(255, 255, 255))
    draw.text(xy, text, fill=(25, 25, 25), font=font)


def render_context(
    source: Path,
    output: Path,
    label: str,
    crop_name: str,
    crop: tuple[int, int, int, int],
    max_long_side: int,
) -> ContextImage:
    arr = read_rgb_image(source)
    height, width = arr.shape[:2]
    scale = min(1.0, float(max_long_side) / float(max(width, height)))
    display = to_display(arr)
    if scale < 1.0:
        display = display.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(display)
    x, y, crop_width, crop_height = crop
    rect = [
        round(x * scale),
        round(y * scale),
        round((x + crop_width) * scale),
        round((y + crop_height) * scale),
    ]
    line_width = max(2, round(max(display.size) / 320))
    for inset in range(line_width):
        draw.rectangle([rect[0] - inset, rect[1] - inset, rect[2] + inset, rect[3] + inset], outline=(255, 212, 0))
    draw_label(draw, (10, 10), label)
    draw_label(draw, (max(10, rect[0] + 6), max(28, rect[1] + 6)), crop_name)

    output.parent.mkdir(parents=True, exist_ok=True)
    display.save(output)
    return ContextImage(
        source=relpath(source),
        output=relpath(output),
        scan_set="",
        set_id="",
        role=label,
        crop_name=crop_name,
        crop=crop,
        source_width=width,
        source_height=height,
        output_width=display.width,
        output_height=display.height,
    )


def candidate_sources(renders_root: Path, registered_root: Path, case: ContextCase) -> list[tuple[str, Path]]:
    slug = local_study.slugify(case.scan_set)
    return [
        ("PS16 reference", renders_root / slug / case.set_id / "ps16.tif"),
        ("RAW61 registered", registered_root / slug / case.set_id / "raw61_registered_to_ps16.tif"),
    ]


def build_contexts(
    cases: list[ContextCase],
    crop: tuple[int, int, int, int],
    crop_name: str,
    renders_root: Path,
    registered_root: Path,
    output_dir: Path,
    max_long_side: int,
) -> list[ContextImage]:
    written: list[ContextImage] = []
    for case in cases:
        slug = local_study.slugify(case.scan_set)
        for role, source in candidate_sources(renders_root, registered_root, case):
            if not source.is_file():
                continue
            role_slug = role.lower().replace(" ", "_")
            output = output_dir / slug / case.set_id / f"{role_slug}_{crop_name}.png"
            record = render_context(source, output, role, crop_name, crop, max_long_side)
            written.append(
                ContextImage(
                    **{
                        **asdict(record),
                        "scan_set": case.scan_set,
                        "set_id": case.set_id,
                    }
                )
            )
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Create small full-frame context images for review-panel crops.")
    parser.add_argument("--case", action="append", type=parse_case, required=True, help='Case as "scan set|set id".')
    parser.add_argument("--crop", type=parse_crop, required=True, help="Crop as x,y,width,height in PS16 coordinates.")
    parser.add_argument("--crop-name", default="manual-01")
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-long-side", type=int, default=900)
    args = parser.parse_args()
    if args.max_long_side <= 0:
        raise SystemExit("--max-long-side must be positive")

    records = build_contexts(
        args.case,
        args.crop,
        args.crop_name,
        args.renders_root,
        args.registered_root,
        args.output_dir,
        args.max_long_side,
    )
    manifest = args.output_dir / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps([asdict(record) for record in records], indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} context image(s) under {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
