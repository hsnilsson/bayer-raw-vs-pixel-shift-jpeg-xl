from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path[:0] = [str(SRC), str(SCRIPTS)]

from break_even_image_tools import (  # noqa: E402
    box_blur_luma,
    crop,
    read_rgb_image,
    resize_rgb,
)
from make_break_even_review_panels import local_align_raw61  # noqa: E402
from make_break_even_review_viewers import display_range, to_display  # noqa: E402
from run_public_latitude_stress import (  # noqa: E402
    build_transforms,
    estimate_linear_exposure_gain,
    linear_luminance,
    linear_rgb,
)


MODE_NAMES = {
    "normal": "Exposure-matched normal",
    "highlight": "Highlight separation",
    "shadow": "Shadow recovery",
}
COMBINER_LABELS = ["Source ARW anchor", "PixelShift2DNG", "Sony ARQ"]


def resolve_path(plan_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (plan_path.parent / path).resolve()


def exposure_matched_rgb(arr: np.ndarray, gain: float) -> np.ndarray:
    values = np.clip(linear_rgb(arr) * np.float32(gain), 0.0, 1.0)
    return np.power(values, np.float32(1.0 / 2.2))


def range_rmse(
    anchor_luma: np.ndarray,
    candidate_luma: np.ndarray,
    low: float,
    high: float,
    *,
    blur_radius: int = 4,
) -> float:
    mask = (anchor_luma >= low) & (anchor_luma <= high)
    if not np.any(mask):
        return 0.0
    anchor_blur = box_blur_luma(anchor_luma, blur_radius)
    candidate_blur = box_blur_luma(candidate_luma, blur_radius)
    return float(np.sqrt(np.mean((candidate_blur[mask] - anchor_blur[mask]) ** 2)))


def detail_correlation(anchor_luma: np.ndarray, candidate_luma: np.ndarray) -> float:
    anchor_highpass = anchor_luma - box_blur_luma(anchor_luma, 2)
    candidate_highpass = candidate_luma - box_blur_luma(candidate_luma, 2)
    anchor_flat = anchor_highpass.reshape(-1)
    candidate_flat = candidate_highpass.reshape(-1)
    if float(anchor_flat.std()) == 0.0 or float(candidate_flat.std()) == 0.0:
        return 0.0
    return float(np.corrcoef(anchor_flat, candidate_flat)[0, 1])


def metric_winner(pixelshift2dng: float, sony: float, *, higher_is_better: bool = False) -> str:
    if math.isclose(pixelshift2dng, sony, rel_tol=1e-6, abs_tol=1e-9):
        return "tie"
    if higher_is_better:
        return "pixelshift2dng" if pixelshift2dng > sony else "sony_arq"
    return "pixelshift2dng" if pixelshift2dng < sony else "sony_arq"


def labeled_panel(images: list[Image.Image], labels: list[str]) -> Image.Image:
    header = 34
    width = sum(image.width for image in images)
    height = header + max(image.height for image in images)
    panel = Image.new("RGB", (width, height), (17, 20, 24))
    draw = ImageDraw.Draw(panel)
    font = ImageFont.load_default()
    left = 0
    for image, label in zip(images, labels, strict=True):
        panel.paste(image, (left, header))
        draw.text((left + 8, 11), label, fill=(255, 255, 255), font=font)
        left += image.width
        if left < width:
            draw.line((left, 0, left, height), fill=(130, 140, 150), width=1)
    return panel


def render_modes(
    anchor: np.ndarray,
    pixelshift2dng: np.ndarray,
    sony: np.ndarray,
    pixelshift2dng_gain: float,
    sony_gain: float,
    output_dir: Path,
    basename: str,
    max_dim: int,
) -> dict[str, str]:
    transforms = {item.name: item for item in build_transforms(anchor)}
    layers_by_mode: dict[str, list[np.ndarray]] = {
        "normal": [
            exposure_matched_rgb(anchor, 1.0),
            exposure_matched_rgb(pixelshift2dng, pixelshift2dng_gain),
            exposure_matched_rgb(sony, sony_gain),
        ]
    }
    for mode, transform_name in {
        "highlight": "highlight_separation_luma_p88_p998",
        "shadow": "shadow_recovery_luma_p12",
    }.items():
        transform = transforms[transform_name]
        if transform.apply_with_linear_gain is None:
            raise RuntimeError(f"transform does not accept exposure gain: {transform_name}")
        layers_by_mode[mode] = [
            transform.apply(anchor),
            transform.apply_with_linear_gain(pixelshift2dng, pixelshift2dng_gain),
            transform.apply_with_linear_gain(sony, sony_gain),
        ]

    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for mode, layers in layers_by_mode.items():
        levels = display_range(layers[0])
        images = [to_display(layer, max_dim, levels) for layer in layers]
        filename = f"{basename}-{mode}.png"
        labeled_panel(images, COMBINER_LABELS).save(output_dir / filename)
        result[mode] = filename
    return result


def evaluate_crop(
    anchor_full: np.ndarray,
    pixelshift2dng_full: np.ndarray,
    sony_full: np.ndarray,
    crop_spec: tuple[int, int, int, int],
    *,
    trim: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    x, y, width, height = crop_spec
    crop_text = ",".join(str(value) for value in crop_spec)
    pixelshift2dng = crop(pixelshift2dng_full, crop_text)
    sony = crop(sony_full, crop_text)
    sony, sony_alignment = local_align_raw61(pixelshift2dng, sony, 32.0)

    scale_x = pixelshift2dng_full.shape[1] / anchor_full.shape[1]
    scale_y = pixelshift2dng_full.shape[0] / anchor_full.shape[0]
    anchor_x = round(x / scale_x)
    anchor_y = round(y / scale_y)
    anchor_width = max(1, round(width / scale_x))
    anchor_height = max(1, round(height / scale_y))
    anchor = crop(anchor_full, f"{anchor_x},{anchor_y},{anchor_width},{anchor_height}")
    anchor = resize_rgb(anchor, (width, height), Image.Resampling.BICUBIC)
    anchor, anchor_alignment = local_align_raw61(pixelshift2dng, anchor, 32.0)

    if trim <= 0 or trim * 2 >= min(width, height):
        raise ValueError("trim must leave a non-empty crop")
    inner = np.s_[trim:-trim, trim:-trim]
    anchor = np.ascontiguousarray(anchor[inner])
    pixelshift2dng = np.ascontiguousarray(pixelshift2dng[inner])
    sony = np.ascontiguousarray(sony[inner])

    pixelshift2dng_gain = estimate_linear_exposure_gain(anchor, pixelshift2dng)
    sony_gain = estimate_linear_exposure_gain(anchor, sony)
    anchor_luma = linear_luminance(anchor)
    pixelshift2dng_luma = linear_luminance(pixelshift2dng) * np.float32(pixelshift2dng_gain)
    sony_luma = linear_luminance(sony) * np.float32(sony_gain)
    bounds = np.percentile(anchor_luma, [0.2, 12.0, 20.0, 80.0, 88.0, 99.8])
    ranges = {
        "shadow": (float(bounds[0]), float(bounds[1])),
        "midtone": (float(bounds[2]), float(bounds[3])),
        "highlight": (float(bounds[4]), float(bounds[5])),
    }
    errors: dict[str, dict[str, object]] = {}
    for name, (low, high) in ranges.items():
        pixelshift2dng_rmse = range_rmse(anchor_luma, pixelshift2dng_luma, low, high)
        sony_rmse = range_rmse(anchor_luma, sony_luma, low, high)
        errors[name] = {
            "pixelshift2dng_rmse": pixelshift2dng_rmse,
            "sony_arq_rmse": sony_rmse,
            "winner": metric_winner(pixelshift2dng_rmse, sony_rmse),
        }

    pixelshift2dng_detail = detail_correlation(anchor_luma, pixelshift2dng_luma)
    sony_detail = detail_correlation(anchor_luma, sony_luma)
    peak = float(np.iinfo(pixelshift2dng.dtype).max)
    metrics: dict[str, object] = {
        "registration": {
            "sony_to_pixelshift2dng": {
                "shift_x_px": sony_alignment.shift_x_px,
                "shift_y_px": sony_alignment.shift_y_px,
                "confidence": sony_alignment.confidence,
                "applied": sony_alignment.applied,
            },
            "anchor_to_pixelshift2dng": {
                "shift_x_px": anchor_alignment.shift_x_px,
                "shift_y_px": anchor_alignment.shift_y_px,
                "confidence": anchor_alignment.confidence,
                "applied": anchor_alignment.applied,
            },
            "trim_px": trim,
        },
        "exposure_match": {
            "pixelshift2dng_gain": pixelshift2dng_gain,
            "pixelshift2dng_ev": float(math.log2(pixelshift2dng_gain)),
            "sony_arq_gain": sony_gain,
            "sony_arq_ev": float(math.log2(sony_gain)),
        },
        "range_errors": errors,
        "detail_correlation": {
            "pixelshift2dng": pixelshift2dng_detail,
            "sony_arq": sony_detail,
            "winner": metric_winner(pixelshift2dng_detail, sony_detail, higher_is_better=True),
        },
        "clipped_pixel_fraction": {
            "pixelshift2dng_low": float(np.mean(np.any(pixelshift2dng <= 0, axis=2))),
            "sony_arq_low": float(np.mean(np.any(sony <= 0, axis=2))),
            "pixelshift2dng_high": float(np.mean(np.any(pixelshift2dng >= peak, axis=2))),
            "sony_arq_high": float(np.mean(np.any(sony >= peak, axis=2))),
        },
    }
    return anchor, pixelshift2dng, sony, metrics


def summarize(cases: list[dict[str, object]]) -> dict[str, object]:
    crop_metrics = [
        crop_item["metrics"]
        for case in cases
        for crop_item in case["crops"]
    ]
    counts: dict[str, dict[str, int]] = {}
    for metric_name in ("shadow", "midtone", "highlight"):
        winners = [item["range_errors"][metric_name]["winner"] for item in crop_metrics]
        counts[metric_name] = {
            "pixelshift2dng": winners.count("pixelshift2dng"),
            "sony_arq": winners.count("sony_arq"),
            "tie": winners.count("tie"),
        }
    detail_winners = [item["detail_correlation"]["winner"] for item in crop_metrics]
    counts["detail"] = {
        "pixelshift2dng": detail_winners.count("pixelshift2dng"),
        "sony_arq": detail_winners.count("sony_arq"),
        "tie": detail_winners.count("tie"),
    }
    pixelshift2dng_ev = [item["exposure_match"]["pixelshift2dng_ev"] for item in crop_metrics]
    sony_ev = [item["exposure_match"]["sony_arq_ev"] for item in crop_metrics]
    return {
        "crop_count": len(crop_metrics),
        "winner_counts": counts,
        "median_exposure_match_ev": {
            "pixelshift2dng": float(np.median(pixelshift2dng_ev)),
            "sony_arq": float(np.median(sony_ev)),
        },
        "latitude_reference_winner": "sony_arq"
        if counts["highlight"]["sony_arq"] > counts["highlight"]["pixelshift2dng"]
        and counts["shadow"]["sony_arq"] > counts["shadow"]["pixelshift2dng"]
        else "inconclusive",
        "detail_winner": "pixelshift2dng"
        if counts["detail"]["pixelshift2dng"] > counts["detail"]["sony_arq"]
        else "sony_arq"
        if counts["detail"]["sony_arq"] > counts["detail"]["pixelshift2dng"]
        else "tie",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare PixelShift2DNG and Sony ARQ renders against a source-ARW tone anchor."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-assets", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--asset-url-prefix", default="assets/pixelshift-combiner-audit")
    parser.add_argument("--panel-dim", type=int, default=480)
    parser.add_argument("--trim", type=int, default=24)
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    public_cases: list[dict[str, object]] = []
    for case in plan.get("cases", []):
        key = str(case["key"])
        anchor_full = read_rgb_image(resolve_path(args.plan, str(case["anchor_render"])))
        pixelshift2dng_full = read_rgb_image(
            resolve_path(args.plan, str(case["pixelshift2dng_render"]))
        )
        sony_full = read_rgb_image(resolve_path(args.plan, str(case["sony_arq_render"])))
        public_crops = []
        for crop_item in case.get("crops", []):
            crop_name = str(crop_item["name"])
            crop_spec = tuple(int(value) for value in crop_item["crop"])
            if len(crop_spec) != 4:
                raise ValueError(f"invalid crop for {key}/{crop_name}")
            anchor, pixelshift2dng, sony, metrics = evaluate_crop(
                anchor_full,
                pixelshift2dng_full,
                sony_full,
                crop_spec,
                trim=args.trim,
            )
            filenames = render_modes(
                anchor,
                pixelshift2dng,
                sony,
                float(metrics["exposure_match"]["pixelshift2dng_gain"]),
                float(metrics["exposure_match"]["sony_arq_gain"]),
                args.output_assets,
                f"{key}-{crop_name}",
                args.panel_dim,
            )
            public_crops.append(
                {
                    "name": crop_name,
                    "crop": list(crop_spec),
                    "images": {
                        mode: f"{args.asset_url_prefix.rstrip('/')}/{filename}"
                        for mode, filename in filenames.items()
                    },
                    "metrics": metrics,
                }
            )
        public_cases.append(
            {
                "key": key,
                "label": str(case["label"]),
                "sequence": str(case["sequence"]),
                "crops": public_crops,
            }
        )

    summary = summarize(public_cases)
    payload = {
        "schema_version": 1,
        "scope": "Two 16-frame sequences rendered through the same RawTherapee 5.12 neutral profile.",
        "method": (
            "Each combiner crop is registered and exposure-matched in linear-luminance midtones to "
            "the first source ARW from the same sequence. A 24 px registration margin is excluded. "
            "Tone RMSE uses a 9x9 low-pass image; detail correlation is reported separately."
        ),
        "mode_labels": MODE_NAMES,
        "combiner_labels": COMBINER_LABELS,
        "summary": summary,
        "cases": public_cases,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output_json}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
