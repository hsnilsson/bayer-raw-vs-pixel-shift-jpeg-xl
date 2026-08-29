from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_break_even_report_site as report_site  # noqa: E402


DEFAULT_CONTEXTS = ROOT / "results/break_even_review_contexts"
DEFAULT_OUTPUT = ROOT / "results/break_even_crop_guides"
MARKER_RGB = (255, 0, 255)
HEADER_HEIGHT = 42


def parse_case(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError('case must be "scan set|set id"')
    return parts[0], parts[1]


def make_guide(source: Path, output: Path, item: dict[str, object]) -> None:
    image = Image.open(source).convert("RGB")
    guide = Image.new("RGB", (image.width, image.height + HEADER_HEIGHT), "white")
    guide.paste(image, (0, HEADER_HEIGHT))
    draw = ImageDraw.Draw(guide)
    draw.text(
        (8, 8),
        "Mark crops with solid pure magenta #FF00FF; one 5x5+ marker per area; multiple allowed",
        fill=(20, 20, 20),
        font=ImageFont.load_default(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    guide.save(output)
    payload = {
        "guide": str(output.relative_to(ROOT)).replace("\\", "/"),
        "source": item["source"],
        "scan_set": item["scan_set"],
        "set_id": item["set_id"],
        "source_width": item["source_width"],
        "source_height": item["source_height"],
        "image_offset": [0, HEADER_HEIGHT],
        "display_width": image.width,
        "display_height": image.height,
        "marker_rgb": list(MARKER_RGB),
    }
    output.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Paint-friendly crop selection guides from PS16 context thumbnails.")
    parser.add_argument("--contexts-root", type=Path, default=DEFAULT_CONTEXTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case", action="append", type=parse_case)
    parser.add_argument("--exclude-cases-file", type=Path, default=report_site.DEFAULT_EXCLUDE_CASES)
    args = parser.parse_args()
    excludes = report_site.read_exclude_cases(args.exclude_cases_file)
    requested = set(args.case or [])
    manifest_path = args.contexts_root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Missing context manifest: {manifest_path}")
    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    seen: set[tuple[str, str]] = set()
    written = 0
    for item in items:
        key = (str(item.get("scan_set", "")), str(item.get("set_id", "")))
        if item.get("role") != "PS16 reference" or key in seen:
            continue
        if requested and key not in requested:
            continue
        if report_site.case_is_excluded(key[0], key[1], excludes):
            continue
        source = ROOT / str(item["output"])
        if not source.is_file():
            continue
        seen.add(key)
        guide = args.output_dir / report_site.local_study.slugify(key[0]) / key[1] / "ps16_guide.png"
        make_guide(source, guide, item)
        written += 1
    print(f"Wrote {written} crop guide(s) to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
