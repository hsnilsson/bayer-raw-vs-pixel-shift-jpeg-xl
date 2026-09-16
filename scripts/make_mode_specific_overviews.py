from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIEWERS = ROOT / "site/assets/review-viewers"
IDENTITY_MODE = "identity"
YELLOW = np.array([255, 212, 0], dtype=np.uint8)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def rgb8(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        return np.ascontiguousarray(np.asarray(source.convert("RGB"), dtype=np.uint8))


def rgb16le_to_rgb8(path: Path, width: int, height: int, levels: tuple[float, float]) -> np.ndarray:
    values = np.fromfile(path, dtype="<u2")
    expected = width * height * 3
    if values.size != expected:
        raise ValueError(f"unexpected RGB16 sample count in {path}: {values.size} != {expected}")
    image = values.reshape(height, width, 3).astype(np.float32) / 65535.0
    low, high = levels
    display = np.clip((image - low) / max(1e-6, high - low), 0.0, 1.0)
    return np.round(display * 255).astype(np.uint8)


def fit_channel_lut(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Fit an 8-bit per-channel tone mapping from a rendered crop pair."""
    if source.shape != target.shape or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError(f"crop shapes must match RGB: {source.shape} vs {target.shape}")
    lut = np.empty((3, 256), dtype=np.uint8)
    grid = np.arange(256, dtype=np.float64)
    for channel in range(3):
        x = source[:, :, channel].reshape(-1)
        y = target[:, :, channel].reshape(-1)
        counts = np.bincount(x, minlength=256)
        sums = np.bincount(x, weights=y, minlength=256)
        known = counts > 0
        if not np.any(known):
            lut[channel] = np.arange(256, dtype=np.uint8)
            continue
        means = sums[known] / counts[known]
        interpolated = np.interp(grid, grid[known], means)
        lut[channel] = np.clip(np.round(interpolated), 0, 255).astype(np.uint8)
    return lut


def apply_channel_lut(image: np.ndarray, lut: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3 or lut.shape != (3, 256):
        raise ValueError("expected an RGB image and a 3x256 LUT")
    output = np.empty_like(image, dtype=np.uint8)
    for channel in range(3):
        output[:, :, channel] = lut[channel][image[:, :, channel]]
    return output


def restore_annotations(image: np.ndarray, identity: np.ndarray, label: str, crop_name: str) -> Image.Image:
    """Restore the navigation overlay after applying a point transform."""
    output = image.copy()
    yellow_mask = np.all(identity == YELLOW, axis=2)
    output[yellow_mask] = identity[yellow_mask]
    rendered = Image.fromarray(output, mode="RGB")
    draw = ImageDraw.Draw(rendered)
    font = ImageFont.load_default()
    text = f"{label} | {crop_name}"
    bbox = draw.textbbox((8, 8), text, font=font)
    draw.rectangle((4, 4, bbox[2] + 5, bbox[3] + 5), fill=(15, 18, 21))
    draw.text((8, 8), text, fill=(255, 255, 255), font=font)
    return rendered


def preview_filename(key: str, mode: str) -> str:
    layer = "reference" if key in {"reference", "ps16_lossless"} else key
    return f"overview_{layer}_{mode}.png"


def save_crop_thumbnail(
    output: Path,
    source: Path,
    *,
    rgb16: bool,
    width: int,
    height: int,
    levels: tuple[float, float],
    force: bool,
) -> bool:
    """Save a compact thumbnail of the crop itself, not its full-frame overview."""
    if output.is_file() and not force:
        return False
    pixels = rgb16le_to_rgb8(source, width, height, levels) if rgb16 else rgb8(source)
    image = Image.fromarray(pixels, mode="RGB")
    image.thumbnail((160, 160), Image.Resampling.LANCZOS)
    image.save(output, optimize=True)
    return True


def generate_viewer_previews(metadata_path: Path, *, force: bool) -> int:
    metadata = read_json(metadata_path)
    directory = metadata_path.parent
    overviews = metadata.get("overviews")
    image_sets = metadata.get("images_by_transform")
    labels = metadata.get("labels", {})
    modes = metadata.get("view_modes")
    crop_name = str(metadata.get("crop_name", ""))
    if not isinstance(overviews, dict) or not isinstance(image_sets, dict) or not isinstance(modes, list):
        return 0
    identity_images = image_sets.get(IDENTITY_MODE)
    rgb16 = metadata.get("rgb16", {})
    rgb16_identity = False
    if not isinstance(identity_images, dict) and isinstance(rgb16, dict):
        sources = rgb16.get("sources")
        transforms = rgb16.get("transforms", [])
        if isinstance(sources, dict) and IDENTITY_MODE in transforms:
            identity_images = sources
            rgb16_identity = True
    if not isinstance(identity_images, dict):
        return 0
    recipe = metadata.get("browser_transform_recipe", {})
    ranges = recipe.get("display_ranges", {}) if isinstance(recipe, dict) else {}
    identity_range = ranges.get(IDENTITY_MODE, [0.0, 1.0]) if isinstance(ranges, dict) else [0.0, 1.0]
    identity_levels = (float(identity_range[0]), float(identity_range[1]))
    rgb16_width = int(rgb16.get("width", 0)) if isinstance(rgb16, dict) else 0
    rgb16_height = int(rgb16.get("height", 0)) if isinstance(rgb16, dict) else 0

    thumbnail_name = "thumbnail_raw61.png"
    raw61_name = identity_images.get("raw61")
    if raw61_name:
        raw61_source = directory / str(raw61_name)
        if raw61_source.is_file():
            save_crop_thumbnail(
                directory / thumbnail_name,
                raw61_source,
                rgb16=rgb16_identity,
                width=rgb16_width,
                height=rgb16_height,
                levels=identity_levels,
                force=force,
            )
            metadata["thumbnail"] = thumbnail_name

    existing_preview_sets = metadata.get("overviews_by_transform", {})
    preview_sets: dict[str, dict[str, str]] = {
        str(mode): {str(key): str(filename) for key, filename in image_set.items()}
        for mode, image_set in existing_preview_sets.items()
        if isinstance(image_set, dict)
    } if isinstance(existing_preview_sets, dict) else {}
    preview_sets[IDENTITY_MODE] = dict(overviews)
    generated = 0
    lut_cache: dict[tuple[Path, Path], np.ndarray] = {}
    image_cache: dict[Path, np.ndarray] = {}

    for mode_item in modes:
        if not isinstance(mode_item, dict):
            continue
        mode = str(mode_item.get("key", ""))
        if not mode or mode == IDENTITY_MODE:
            continue
        mode_images = image_sets.get(mode)
        if not isinstance(mode_images, dict):
            continue
        mode_overviews: dict[str, str] = {}
        for key, overview_name in overviews.items():
            key = str(key)
            identity_crop_name = identity_images.get(key)
            target_crop_name = mode_images.get(key)
            if not identity_crop_name or not target_crop_name or not overview_name:
                continue
            identity_crop = directory / str(identity_crop_name)
            target_crop = directory / str(target_crop_name)
            identity_overview = directory / str(overview_name)
            if not identity_crop.is_file() or not target_crop.is_file() or not identity_overview.is_file():
                continue
            output_name = preview_filename(key, mode)
            output = directory / output_name
            mode_overviews[key] = output_name
            if output.is_file() and not force:
                continue
            crop_pair = (identity_crop, target_crop)
            if crop_pair not in lut_cache:
                identity_pixels = (
                    rgb16le_to_rgb8(identity_crop, rgb16_width, rgb16_height, identity_levels)
                    if rgb16_identity
                    else rgb8(identity_crop)
                )
                lut_cache[crop_pair] = fit_channel_lut(identity_pixels, rgb8(target_crop))
            if identity_overview not in image_cache:
                image_cache[identity_overview] = rgb8(identity_overview)
            base = image_cache[identity_overview]
            transformed = apply_channel_lut(base, lut_cache[crop_pair])
            label = str(labels.get(key, key.replace("_", " ").upper())) if isinstance(labels, dict) else key
            restore_annotations(transformed, base, label, crop_name).save(output, optimize=True)
            generated += 1
        if mode_overviews:
            preview_sets[mode] = mode_overviews

    metadata["overviews_by_transform"] = preview_sets
    metadata["overview_preview_generation"] = {
        "generator": str(Path(__file__).relative_to(ROOT)),
        "method": "per-channel 8-bit LUT fitted from each identity/transformed crop pair",
        "purpose": "navigation context only; crop images remain the measurement and inspection source",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate small dropdown-aware overview images from the existing rendered crop pairs."
    )
    parser.add_argument("--viewers", type=Path, default=DEFAULT_VIEWERS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    metadata_paths = sorted(args.viewers.rglob("metadata.json"))
    if not metadata_paths:
        raise SystemExit("no viewer metadata found")
    generated = 0
    for index, metadata_path in enumerate(metadata_paths, start=1):
        count = generate_viewer_previews(metadata_path, force=args.force)
        generated += count
        print(f"[{index}/{len(metadata_paths)}] {metadata_path.parent.relative_to(args.viewers)}: {count}", flush=True)
    print(f"Generated {generated} mode-specific overview image(s) for {len(metadata_paths)} viewer(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
