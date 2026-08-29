from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GUIDES = ROOT / "results/break_even_crop_guides"
DEFAULT_OUTPUT = DEFAULT_GUIDES / "crop_plan.json"
MARKER_RGB = (255, 0, 255)


def connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for y, x in zip(*np.where(mask & ~seen)):
        if seen[y, x]:
            continue
        queue = deque([(int(y), int(x))])
        seen[y, x] = True
        component: list[tuple[int, int]] = []
        while queue:
            cy, cx = queue.popleft()
            component.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        components.append(component)
    return components


def marker_crops(
    guide: np.ndarray,
    metadata: dict[str, object],
    crop_size: int,
    minimum_marker_pixels: int,
) -> list[dict[str, object]]:
    marker = np.all(guide[:, :, :3] == np.array(metadata.get("marker_rgb", MARKER_RGB)), axis=2)
    components = [component for component in connected_components(marker) if len(component) >= minimum_marker_pixels]
    offset_x, offset_y = [int(value) for value in metadata.get("image_offset", [0, 0])]
    display_width = int(metadata["display_width"])
    display_height = int(metadata["display_height"])
    source_width = int(metadata["source_width"])
    source_height = int(metadata["source_height"])
    size = min(crop_size, source_width, source_height)
    crops: list[dict[str, object]] = []
    for index, component in enumerate(sorted(components, key=lambda values: (min(y for y, _ in values), min(x for _, x in values))), 1):
        display_y = sum(y for y, _ in component) / len(component) - offset_y
        display_x = sum(x for _, x in component) / len(component) - offset_x
        source_x = round(display_x / display_width * source_width)
        source_y = round(display_y / display_height * source_height)
        left = min(max(source_x - size // 2, 0), max(source_width - size, 0))
        top = min(max(source_y - size // 2, 0), max(source_height - size, 0))
        crops.append({"name": f"manual-{index:02d}", "crop": [left, top, size, size], "marker_display": [round(display_x), round(display_y)]})
    return crops


def main() -> int:
    parser = argparse.ArgumentParser(description="Read pure-magenta crop markers from selection guides.")
    parser.add_argument("--guides-root", type=Path, default=DEFAULT_GUIDES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--crop-size", type=int, default=768)
    parser.add_argument("--minimum-marker-pixels", type=int, default=4)
    args = parser.parse_args()
    if args.crop_size <= 0 or args.minimum_marker_pixels <= 0:
        raise SystemExit("--crop-size and --minimum-marker-pixels must be positive")
    plan: dict[str, object] = {"marker_rgb": list(MARKER_RGB), "crop_size": args.crop_size, "cases": {}}
    for metadata_path in sorted(args.guides_root.rglob("*.json")):
        if metadata_path.name == args.output.name:
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        guide_path = metadata_path.with_suffix(".png")
        if not guide_path.is_file():
            continue
        guide = np.asarray(Image.open(guide_path).convert("RGB"))
        crops = marker_crops(guide, metadata, args.crop_size, args.minimum_marker_pixels)
        key = f'{metadata["scan_set"]}|{metadata["set_id"]}'
        plan["cases"][key] = {"scan_set": metadata["scan_set"], "set_id": metadata["set_id"], "guide": str(guide_path.relative_to(ROOT)).replace("\\", "/"), "crops": crops}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Wrote crop plan {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
