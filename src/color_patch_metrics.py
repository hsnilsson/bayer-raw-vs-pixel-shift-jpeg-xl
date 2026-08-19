from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class RgbColorSpace:
    name: str
    rgb_to_xyz: np.ndarray
    whitepoint: np.ndarray


COLOR_SPACES: dict[str, RgbColorSpace] = {
    "srgb": RgbColorSpace(
        name="srgb",
        rgb_to_xyz=np.array(
            [
                [0.4124564, 0.3575761, 0.1804375],
                [0.2126729, 0.7151522, 0.0721750],
                [0.0193339, 0.1191920, 0.9503041],
            ],
            dtype=np.float64,
        ),
        whitepoint=np.array([0.95047, 1.0, 1.08883], dtype=np.float64),
    ),
    "display-p3": RgbColorSpace(
        name="display-p3",
        rgb_to_xyz=np.array(
            [
                [0.48657095, 0.26566769, 0.19821729],
                [0.22897456, 0.69173852, 0.07928691],
                [0.00000000, 0.04511338, 1.04394437],
            ],
            dtype=np.float64,
        ),
        whitepoint=np.array([0.95047, 1.0, 1.08883], dtype=np.float64),
    ),
    "adobe-rgb": RgbColorSpace(
        name="adobe-rgb",
        rgb_to_xyz=np.array(
            [
                [0.5767309, 0.1855540, 0.1881852],
                [0.2973769, 0.6273491, 0.0752741],
                [0.0270343, 0.0706872, 0.9911085],
            ],
            dtype=np.float64,
        ),
        whitepoint=np.array([0.95047, 1.0, 1.08883], dtype=np.float64),
    ),
    "prophoto-rgb": RgbColorSpace(
        name="prophoto-rgb",
        rgb_to_xyz=np.array(
            [
                [0.7976749, 0.1351917, 0.0313534],
                [0.2880402, 0.7118741, 0.0000857],
                [0.0000000, 0.0000000, 0.8252100],
            ],
            dtype=np.float64,
        ),
        whitepoint=np.array([0.96422, 1.0, 0.82521], dtype=np.float64),
    ),
}


def color_space_names() -> list[str]:
    return sorted(COLOR_SPACES)


def color_space(name: str) -> RgbColorSpace:
    key = name.lower()
    if key not in COLOR_SPACES:
        raise ValueError(f"unknown RGB color space: {name}")
    return COLOR_SPACES[key]


def as_linear_unit_rgb(values: np.ndarray) -> np.ndarray:
    if values.ndim != 3 or values.shape[2] < 3:
        raise ValueError(f"expected an RGB image with shape HxWx3, got {values.shape}")
    arr = values[:, :, :3]
    if np.issubdtype(arr.dtype, np.integer):
        peak = np.iinfo(arr.dtype).max
        arr = arr.astype(np.float64) / float(peak)
    else:
        arr = arr.astype(np.float64, copy=False)
    return np.nan_to_num(np.clip(arr, 0.0, 1.0), nan=0.0, posinf=1.0, neginf=0.0)


def linear_rgb_to_xyz(values: np.ndarray, rgb_space: str = "srgb") -> np.ndarray:
    space = color_space(rgb_space)
    return np.asarray(values, dtype=np.float64) @ space.rgb_to_xyz.T


def xyz_to_lab(values: np.ndarray, rgb_space: str = "srgb") -> np.ndarray:
    space = color_space(rgb_space)
    xyz = np.asarray(values, dtype=np.float64) / space.whitepoint
    delta = 6.0 / 29.0
    delta3 = delta**3
    f = np.where(xyz > delta3, np.cbrt(xyz), xyz / (3.0 * delta**2) + 4.0 / 29.0)
    lab = np.empty_like(f)
    lab[..., 0] = 116.0 * f[..., 1] - 16.0
    lab[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return lab


def linear_rgb_to_lab(values: np.ndarray, rgb_space: str = "srgb") -> np.ndarray:
    return xyz_to_lab(linear_rgb_to_xyz(values, rgb_space), rgb_space)


def delta_e_2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = np.moveaxis(first, -1, 0)
    l2, a2, b2 = np.moveaxis(second, -1, 0)

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar7 = c_bar**7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))

    a1_prime = (1.0 + g) * a1
    a2_prime = (1.0 + g) * a2
    c1_prime = np.hypot(a1_prime, b1)
    c2_prime = np.hypot(a2_prime, b2)

    h1_prime = np.degrees(np.arctan2(b1, a1_prime)) % 360.0
    h2_prime = np.degrees(np.arctan2(b2, a2_prime)) % 360.0
    h1_prime = np.where(c1_prime == 0.0, 0.0, h1_prime)
    h2_prime = np.where(c2_prime == 0.0, 0.0, h2_prime)

    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime

    delta_h_prime = h2_prime - h1_prime
    delta_h_prime = np.where(delta_h_prime > 180.0, delta_h_prime - 360.0, delta_h_prime)
    delta_h_prime = np.where(delta_h_prime < -180.0, delta_h_prime + 360.0, delta_h_prime)
    delta_h_prime = np.where(c1_prime * c2_prime == 0.0, 0.0, delta_h_prime)
    delta_h_term = 2.0 * np.sqrt(c1_prime * c2_prime) * np.sin(np.radians(delta_h_prime / 2.0))

    l_bar_prime = (l1 + l2) / 2.0
    c_bar_prime = (c1_prime + c2_prime) / 2.0

    h_sum = h1_prime + h2_prime
    h_diff = np.abs(h1_prime - h2_prime)
    h_bar_prime = np.where(
        c1_prime * c2_prime == 0.0,
        h_sum,
        np.where(
            h_diff <= 180.0,
            h_sum / 2.0,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar_prime - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar_prime))
        + 0.32 * np.cos(np.radians(3.0 * h_bar_prime + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar_prime - 63.0))
    )
    delta_theta = 30.0 * np.exp(-((h_bar_prime - 275.0) / 25.0) ** 2)
    c_bar_prime7 = c_bar_prime**7
    r_c = 2.0 * np.sqrt(c_bar_prime7 / (c_bar_prime7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar_prime - 50.0) ** 2) / np.sqrt(
        20.0 + (l_bar_prime - 50.0) ** 2
    )
    s_c = 1.0 + 0.045 * c_bar_prime
    s_h = 1.0 + 0.015 * c_bar_prime * t
    r_t = -np.sin(np.radians(2.0 * delta_theta)) * r_c

    l_term = delta_l_prime / s_l
    c_term = delta_c_prime / s_c
    h_term = delta_h_term / s_h
    return np.sqrt(l_term**2 + c_term**2 + h_term**2 + r_t * c_term * h_term)


def patch_rectangles(
    height: int,
    width: int,
    patch_size: int,
    min_patch_size: int | None = None,
) -> Iterable[tuple[int, int, int, int]]:
    if patch_size <= 0:
        raise ValueError("patch_size must be positive")
    min_size = min_patch_size if min_patch_size is not None else max(1, patch_size // 2)
    for y in range(0, height, patch_size):
        patch_height = min(patch_size, height - y)
        if patch_height < min_size:
            continue
        for x in range(0, width, patch_size):
            patch_width = min(patch_size, width - x)
            if patch_width < min_size:
                continue
            yield x, y, patch_width, patch_height


def _lab_bins(lab: np.ndarray) -> tuple[str, str]:
    lightness = float(lab[0])
    chroma = float(math.hypot(float(lab[1]), float(lab[2])))
    if lightness < 25.0:
        luminance_bin = "dark"
    elif lightness < 75.0:
        luminance_bin = "mid"
    else:
        luminance_bin = "light"

    if chroma < 10.0:
        chroma_bin = "neutral"
    elif chroma < 35.0:
        chroma_bin = "moderate"
    else:
        chroma_bin = "saturated"
    return luminance_bin, chroma_bin


def patch_metric_rows(
    reference: np.ndarray,
    candidate: np.ndarray,
    patch_size: int = 256,
    rgb_space: str = "srgb",
) -> list[dict[str, Any]]:
    ref = as_linear_unit_rgb(reference)
    cand = as_linear_unit_rgb(candidate)
    if ref.shape != cand.shape:
        raise ValueError(f"reference and candidate shapes differ: {ref.shape} != {cand.shape}")

    space = color_space(rgb_space)
    luma_weights = space.rgb_to_xyz[1]
    rows: list[dict[str, Any]] = []
    patch_id = 0
    for x, y, width, height in patch_rectangles(ref.shape[0], ref.shape[1], patch_size):
        ref_patch = ref[y : y + height, x : x + width]
        cand_patch = cand[y : y + height, x : x + width]
        ref_mean = ref_patch.reshape(-1, 3).mean(axis=0)
        cand_mean = cand_patch.reshape(-1, 3).mean(axis=0)
        ref_lab = linear_rgb_to_lab(ref_mean, rgb_space)
        cand_lab = linear_rgb_to_lab(cand_mean, rgb_space)
        delta_e = float(delta_e_2000(ref_lab, cand_lab))
        ref_luma = ref_patch @ luma_weights
        cand_luma = cand_patch @ luma_weights
        diff = cand_patch - ref_patch
        luma_diff = cand_luma - ref_luma
        ref_luma_std = float(ref_luma.std())
        cand_luma_std = float(cand_luma.std())
        error_luma_rmse = float(np.sqrt(np.mean(luma_diff * luma_diff)))
        error_rgb_rmse = float(np.sqrt(np.mean(diff * diff)))
        mean_bias = cand_mean - ref_mean
        ref_rgb_std = ref_patch.reshape(-1, 3).std(axis=0)
        cand_rgb_std = cand_patch.reshape(-1, 3).std(axis=0)
        luminance_bin, chroma_bin = _lab_bins(ref_lab)

        rows.append(
            {
                "patch_id": patch_id,
                "patch_x": x,
                "patch_y": y,
                "patch_width": width,
                "patch_height": height,
                "patch_pixels": width * height,
                "comparison_rgb_space": space.name,
                "delta_e00": delta_e,
                "ref_lab_l": float(ref_lab[0]),
                "ref_lab_a": float(ref_lab[1]),
                "ref_lab_b": float(ref_lab[2]),
                "cand_lab_l": float(cand_lab[0]),
                "cand_lab_a": float(cand_lab[1]),
                "cand_lab_b": float(cand_lab[2]),
                "ref_chroma": float(math.hypot(float(ref_lab[1]), float(ref_lab[2]))),
                "luminance_bin": luminance_bin,
                "chroma_bin": chroma_bin,
                "mean_bias_r_16bit": float(mean_bias[0] * 65535.0),
                "mean_bias_g_16bit": float(mean_bias[1] * 65535.0),
                "mean_bias_b_16bit": float(mean_bias[2] * 65535.0),
                "mean_abs_bias_16bit": float(np.mean(np.abs(mean_bias)) * 65535.0),
                "error_rgb_rmse_16bit": error_rgb_rmse * 65535.0,
                "error_luma_rmse_16bit": error_luma_rmse * 65535.0,
                "ref_luma_std_16bit": ref_luma_std * 65535.0,
                "cand_luma_std_16bit": cand_luma_std * 65535.0,
                "error_to_ref_luma_std": float("inf")
                if ref_luma_std == 0.0
                else error_luma_rmse / ref_luma_std,
                "ref_rgb_std_mean_16bit": float(ref_rgb_std.mean() * 65535.0),
                "cand_rgb_std_mean_16bit": float(cand_rgb_std.mean() * 65535.0),
            }
        )
        patch_id += 1
    return rows


def summarize_patch_metric_rows(
    rows: list[dict[str, Any]],
    group_keys: tuple[str, ...] = ("level", "transform"),
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(key_name, "")) for key_name in group_keys)
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        delta_e = np.array([float(row["delta_e00"]) for row in group], dtype=np.float64)
        error_to_noise = np.array(
            [float(row["error_to_ref_luma_std"]) for row in group], dtype=np.float64
        )
        finite_error_to_noise = error_to_noise[np.isfinite(error_to_noise)]
        summary: dict[str, Any] = {name: value for name, value in zip(group_keys, key)}
        summary.update(
            {
                "patches": len(group),
                "median_delta_e00": float(np.median(delta_e)),
                "mean_delta_e00": float(np.mean(delta_e)),
                "p95_delta_e00": float(np.percentile(delta_e, 95)),
                "max_delta_e00": float(np.max(delta_e)),
                "mean_abs_bias_16bit": float(
                    np.mean([float(row["mean_abs_bias_16bit"]) for row in group])
                ),
                "mean_error_rgb_rmse_16bit": float(
                    np.mean([float(row["error_rgb_rmse_16bit"]) for row in group])
                ),
                "mean_bias_r_16bit": float(
                    np.mean([float(row["mean_bias_r_16bit"]) for row in group])
                ),
                "mean_bias_g_16bit": float(
                    np.mean([float(row["mean_bias_g_16bit"]) for row in group])
                ),
                "mean_bias_b_16bit": float(
                    np.mean([float(row["mean_bias_b_16bit"]) for row in group])
                ),
                "median_error_to_ref_luma_std": float(np.median(finite_error_to_noise))
                if finite_error_to_noise.size
                else float("inf"),
            }
        )
        summaries.append(summary)
    return summaries
