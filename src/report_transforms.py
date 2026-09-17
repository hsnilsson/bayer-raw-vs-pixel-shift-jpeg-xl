"""Shared, explicitly linear-light report measurements and browser recipes."""
from __future__ import annotations

from dataclasses import asdict
import math

import numpy as np
from PIL import Image

from break_even_image_tools import structure_metrics, phase_correlation_shift
from color_patch_metrics import delta_e_2000
from image_color import RgbProfile, lab_from_linear

MODES = {
    "identity": ("Normal", "ICC-managed rendered RGB; no automatic display stretch."),
    "shadow_recovery_luma_p12": ("Shadow recovery", "Expands the reference's darkest 12% of linear luminance as grayscale. Shared calibration; no candidate exposure fitting."),
    "highlight_separation_luma_p88_p998": ("Highlight separation", "Expands reference linear luminance between percentiles 88 and 99.8 as grayscale. Shared calibration; no candidate exposure fitting."),
    "negative_density_hard_print": ("Hard negative-density inversion", "Reference-normalized linear RGB transmission, log density, fixed channel balance and strong contrast. A mathematical stress proxy, not a film-specific inversion."),
    "negative_density_hard_shadow_recovery": ("Hard inversion with shadow lift", "The same density proxy with a fixed lift of its lower positive values. This measures edit sensitivity, not recovered capture latitude."),
}


def recipe_for(reference_linear: np.ndarray, profile: RgbProfile) -> dict:
    black, base = np.percentile(reference_linear, [.3, 99.7], axis=(0, 1))
    density = -np.log(np.clip((reference_linear - black) / np.maximum(base - black, 1e-6), 1e-5, 1))
    low, high = np.percentile(density, [.5, 99.5], axis=(0, 1))
    weights = profile.matrix[1]
    y = reference_linear @ weights
    shadow, hi_black, hi_white = np.percentile(y, [12, 88, 99.8])
    return {"schema": 3, "domain": "ICC linear RGB", "profile": profile.recipe(),
            "luma_weights": weights.tolist(), "shadow_white": max(float(shadow), 1e-6),
            "highlight_black": float(hi_black), "highlight_white": max(float(hi_white), float(hi_black) + 1e-6),
            "density_black": black.tolist(), "density_base": base.tolist(),
            "density_low": low.tolist(), "density_high": high.tolist(),
            "exposure_domain": "linear RGB before stress transform", "candidate_fit": "none"}


def transform(linear: np.ndarray, name: str, recipe: dict) -> np.ndarray:
    if name == "identity":
        return linear
    if name in ("shadow_recovery_luma_p12", "highlight_separation_luma_p88_p998"):
        y = linear @ np.asarray(recipe["luma_weights"])
        if name == "shadow_recovery_luma_p12":
            y = y / recipe["shadow_white"]
        else:
            y = (y - recipe["highlight_black"]) / (recipe["highlight_white"] - recipe["highlight_black"])
        return np.repeat(np.clip(y, 0, 1)[..., None], 3, axis=2).astype(np.float32)
    if name not in ("negative_density_hard_print", "negative_density_hard_shadow_recovery"):
        raise ValueError(f"Undeclared transform: {name}")
    black, base, low, high = [np.asarray(recipe[k]) for k in ("density_black", "density_base", "density_low", "density_high")]
    transmission = np.clip((linear - black) / np.maximum(base - black, 1e-6), 1e-5, 1)
    y = np.clip((-np.log(transmission) - low) / np.maximum(high - low, 1e-6), 0, 1)
    y = np.clip((y - .035) / .90, 0, 1)
    if name.endswith("shadow_recovery"):
        y = y ** .68
    y = np.clip(y * np.array([1.07, 1, .94]), 0, 1)
    lo, hi = 1 / (1 + math.exp(4.5)), 1 / (1 + math.exp(-4.5))
    return ((1 / (1 + np.exp(-9 * (y - .5))) - lo) / (hi - lo)).astype(np.float32)


def patch_means(linear: np.ndarray, size: int = 64) -> np.ndarray:
    h, w = linear.shape[:2]
    return np.array([linear[y:min(y+size,h), x:min(x+size,w)].mean(axis=(0, 1), dtype=np.float64)
                     for y in range(0, h, size) for x in range(0, w, size)])


def measure(reference_linear: np.ndarray, candidate_linear: np.ndarray, profile: RgbProfile,
            recipe: dict, modes: tuple[str, ...] = tuple(MODES)) -> list[dict]:
    if reference_linear.shape != candidate_linear.shape:
        raise ValueError("Measurement inputs must share shape and valid region")
    result = []
    for name in modes:
        ref, cand = transform(reference_linear, name, recipe), transform(candidate_linear, name, recipe)
        diff = np.asarray(cand, dtype=np.float64) - ref
        de = delta_e_2000(lab_from_linear(patch_means(ref), profile), lab_from_linear(patch_means(cand), profile))
        structure = asdict(structure_metrics(ref, cand, luma_weights=tuple(profile.matrix[1])))
        structure = {k: v if math.isfinite(v) else None for k, v in structure.items()}
        result.append({"transform": name, "patch_size": 64, "patch_count": int(de.size),
                       "delta_e00_p95": float(np.percentile(de, 95)), "delta_e00_max": float(de.max()),
                       "linear_rmse": float(np.sqrt(np.mean(diff * diff))),
                       "linear_mae": float(np.abs(diff).mean()),
                       "channel_bias_max": float(np.max(np.abs(diff.mean(axis=(0,1))))),
                       "clip_fraction": float(np.mean((cand <= 0) | (cand >= 1))),
                       "reference_clip_fraction": float(np.mean((ref <= 0) | (ref >= 1))), **structure})
    return result


def reduce_linear(encoded: np.ndarray, profile: RgbProfile, factor: int = 10) -> np.ndarray:
    """Exact nonoverlapping box means in linear light, with bounded tile memory.

    Discard fewer than factor bottom/right pixels; the returned scope records
    these bounds. No quantization occurs before the measurement.
    """
    h, w = encoded.shape[0] // factor, encoded.shape[1] // factor
    out = np.empty((h, w, 3), np.float32)
    for y in range(0, h, 16):
        end = min(y + 16, h)
        block = profile.linearize(encoded[y*factor:end*factor, :w*factor])
        out[y:end] = block.reshape(end-y, factor, w, factor, 3).mean(axis=(1,3), dtype=np.float64)
    return out


def resize_linear(linear: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.stack([np.asarray(Image.fromarray(linear[..., i]).resize(size, Image.Resampling.BICUBIC)) for i in range(3)], axis=2)


def sample_raw_crop(raw: np.ndarray, profile: RgbProfile, crop: tuple[int, int, int, int],
                    reference_shape: tuple[int, ...], global_shift: tuple[float, float]) -> np.ndarray:
    """Resample only needed RAW render pixels, in linear light, onto the PS16 grid."""
    x, y, w, h = crop
    sx, sy = raw.shape[1] / reference_shape[1], raw.shape[0] / reference_shape[0]
    gx, gy = global_shift
    left, top = max(0, math.floor((x-gx)*sx)-4), max(0, math.floor((y-gy)*sy)-4)
    right, bottom = min(raw.shape[1], math.ceil((x+w-gx)*sx)+4), min(raw.shape[0], math.ceil((y+h-gy)*sy)+4)
    values = profile.linearize(raw[top:bottom, left:right])
    affine = (sx, 0, (x-gx)*sx-left, 0, sy, (y-gy)*sy-top)
    return np.stack([np.asarray(Image.fromarray(values[..., i]).transform((w,h), Image.Transform.AFFINE,
                    affine, Image.Resampling.BICUBIC)) for i in range(3)], axis=2)


def align_scope(ref: np.ndarray, raw: np.ndarray, profile: RgbProfile, max_shift: int = 32) -> tuple[np.ndarray, dict]:
    dx, dy, peak, confidence = phase_correlation_shift(ref @ profile.matrix[1], raw @ profile.matrix[1])
    applied = confidence > 20 and abs(dx) <= max_shift and abs(dy) <= max_shift
    ix, iy = (int(dx), int(dy)) if applied else (0, 0)
    aligned = np.roll(raw, (iy, ix), axis=(0, 1))
    # Common valid support excludes both fill and the high-pass filter boundary.
    margin = 2
    valid = [max(ix,0)+margin, max(iy,0)+margin,
             raw.shape[1]-abs(ix)-2*margin, raw.shape[0]-abs(iy)-2*margin]
    return aligned, {"shift_x_px": dx, "shift_y_px": dy, "confidence": confidence,
                     "phase_peak": peak, "applied": applied, "valid_xywh": valid,
                     "valid_fraction": valid[2]*valid[3]/(raw.shape[0]*raw.shape[1])}
