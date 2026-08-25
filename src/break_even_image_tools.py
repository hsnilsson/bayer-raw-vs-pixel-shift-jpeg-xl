from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RegistrationResult:
    scale_x: float
    scale_y: float
    shift_x_px: float
    shift_y_px: float
    overlap_fraction: float
    phase_peak: float
    phase_peak_to_median: float
    reference_shape: tuple[int, int, int]
    candidate_shape: tuple[int, int, int]


@dataclass(frozen=True)
class StructureMetrics:
    highpass_rmse: float
    highpass_reference_rms: float
    structure_loss: float
    detail_correlation: float
    detail_energy_ratio: float


def import_tifffile():
    try:
        import tifffile  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This operation needs tifffile for reliable 16-bit RGB TIFF I/O. "
            'Install optional dependencies with: python -m pip install -e ".[tiff]"'
        ) from exc
    return tifffile


def optional_tifffile():
    for path in [os.environ.get("JXL_PYDEPS"), str(ROOT / ".deps/jxl_pydeps")]:
        if path and Path(path).is_dir() and path not in sys.path:
            sys.path.insert(0, path)
    try:
        import tifffile  # type: ignore
    except ModuleNotFoundError:
        return None
    if not hasattr(tifffile, "imread") or not hasattr(tifffile, "imwrite"):
        return None
    return tifffile


def read_rgb_image(path: Path) -> np.ndarray:
    tifffile = optional_tifffile()
    if tifffile is not None:
        arr = tifffile.imread(path)
    else:
        arr = np.asarray(Image.open(path))
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim != 3:
        raise ValueError(f"expected 2D/RGB image, got shape {arr.shape}: {path}")
    if arr.shape[2] > 3:
        arr = arr[:, :, :3]
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    if arr.dtype.byteorder == ">":
        arr = arr.astype(arr.dtype.newbyteorder("="), copy=False)
    if arr.dtype not in (np.uint8, np.uint16):
        values = arr.astype(np.float64)
        low = float(values.min(initial=0.0))
        high = float(values.max(initial=0.0))
        if high > low:
            values = (values - low) / (high - low)
        arr = np.round(np.clip(values, 0.0, 1.0) * 65535.0).astype(np.uint16)
    return np.ascontiguousarray(arr[:, :, :3])


def write_rgb_tiff(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile = optional_tifffile()
    if tifffile is not None:
        tifffile.imwrite(path, np.ascontiguousarray(arr), photometric="rgb")
        return
    if arr.dtype != np.uint8:
        raise RuntimeError(
            "Writing 16-bit RGB TIFF needs tifffile. "
            'Install optional dependencies with: python -m pip install -e ".[tiff]"'
        )
    Image.fromarray(np.ascontiguousarray(arr[:, :, :3])).save(path)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resize_channel(channel: np.ndarray, size: tuple[int, int], resample: int) -> np.ndarray:
    if channel.dtype == np.uint16:
        image = Image.fromarray(channel, mode="I;16")
        return np.asarray(image.resize(size, resample=resample), dtype=np.uint16)
    image = Image.fromarray(channel)
    return np.asarray(image.resize(size, resample=resample), dtype=channel.dtype)


def resize_rgb(arr: np.ndarray, size: tuple[int, int], resample: int = Image.Resampling.BICUBIC) -> np.ndarray:
    width, height = size
    if arr.shape[1] == width and arr.shape[0] == height:
        return np.ascontiguousarray(arr[:, :, :3])
    channels = [_resize_channel(arr[:, :, idx], size, resample) for idx in range(3)]
    return np.ascontiguousarray(np.stack(channels, axis=2))


def shift_rgb(arr: np.ndarray, shift_x: float, shift_y: float, fill: int = 0) -> np.ndarray:
    height, width = arr.shape[:2]
    channels = []
    for idx in range(3):
        channel = arr[:, :, idx]
        if channel.dtype == np.uint16:
            image = Image.fromarray(channel, mode="I;16")
        else:
            image = Image.fromarray(channel)
        shifted = image.transform(
            (width, height),
            Image.Transform.AFFINE,
            (1.0, 0.0, -shift_x, 0.0, 1.0, -shift_y),
            resample=Image.Resampling.BICUBIC,
            fillcolor=fill,
        )
        channels.append(np.asarray(shifted, dtype=channel.dtype))
    return np.ascontiguousarray(np.stack(channels, axis=2))


def unit_luma(arr: np.ndarray) -> np.ndarray:
    rgb = arr[:, :, :3].astype(np.float32)
    peak = float(np.iinfo(arr.dtype).max) if np.issubdtype(arr.dtype, np.integer) else 1.0
    rgb = np.clip(rgb / peak, 0.0, 1.0)
    return rgb[:, :, 0] * 0.2126 + rgb[:, :, 1] * 0.7152 + rgb[:, :, 2] * 0.0722


def preview_luma(arr: np.ndarray, max_dim: int = 2048) -> np.ndarray:
    luma = unit_luma(arr)
    height, width = luma.shape
    scale = min(1.0, float(max_dim) / float(max(height, width)))
    if scale >= 1.0:
        return luma.astype(np.float32, copy=False)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    image = Image.fromarray(np.asarray(luma * 65535.0, dtype=np.uint16), mode="I;16")
    resized = image.resize(size, resample=Image.Resampling.BOX)
    return np.asarray(resized, dtype=np.float32) / 65535.0


def phase_correlation_shift(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float, float, float]:
    if reference.shape != candidate.shape:
        raise ValueError(f"phase correlation shapes differ: {reference.shape} != {candidate.shape}")
    ref = reference.astype(np.float64, copy=False)
    cand = candidate.astype(np.float64, copy=False)
    ref = ref - ref.mean()
    cand = cand - cand.mean()
    if not np.any(ref) or not np.any(cand):
        return 0.0, 0.0, 0.0, 0.0

    window_y = np.hanning(ref.shape[0])[:, None]
    window_x = np.hanning(ref.shape[1])[None, :]
    window = window_y * window_x
    cross_power = np.fft.fft2(ref * window) * np.conj(np.fft.fft2(cand * window))
    magnitude = np.abs(cross_power)
    cross_power = cross_power / np.maximum(magnitude, 1e-12)
    corr = np.fft.ifft2(cross_power).real
    peak_y, peak_x = np.unravel_index(int(np.argmax(corr)), corr.shape)
    if peak_y > corr.shape[0] // 2:
        peak_y -= corr.shape[0]
    if peak_x > corr.shape[1] // 2:
        peak_x -= corr.shape[1]
    peak = float(corr.max(initial=0.0))
    median = float(np.median(np.abs(corr)))
    confidence = peak / max(median, 1e-12)
    return float(peak_x), float(peak_y), peak, confidence


def overlap_fraction(width: int, height: int, shift_x: float, shift_y: float) -> float:
    overlap_w = max(0.0, float(width) - abs(float(shift_x)))
    overlap_h = max(0.0, float(height) - abs(float(shift_y)))
    return (overlap_w * overlap_h) / float(width * height)


def register_candidate_to_reference(
    reference: np.ndarray,
    candidate: np.ndarray,
    max_preview_dim: int = 2048,
) -> tuple[np.ndarray, RegistrationResult]:
    ref_h, ref_w = reference.shape[:2]
    cand_h, cand_w = candidate.shape[:2]
    scale_x = ref_w / cand_w
    scale_y = ref_h / cand_h

    ref_preview = preview_luma(reference, max_preview_dim)
    candidate_preview_size = (ref_preview.shape[1], ref_preview.shape[0])
    cand_preview_rgb = resize_rgb(candidate, candidate_preview_size, resample=Image.Resampling.BOX)
    cand_preview = unit_luma(cand_preview_rgb)

    preview_shift_x, preview_shift_y, peak, confidence = phase_correlation_shift(
        ref_preview, cand_preview
    )
    shift_x = preview_shift_x * (ref_w / ref_preview.shape[1])
    shift_y = preview_shift_y * (ref_h / ref_preview.shape[0])

    scaled = resize_rgb(candidate, (ref_w, ref_h))
    registered = shift_rgb(scaled, shift_x, shift_y)
    result = RegistrationResult(
        scale_x=scale_x,
        scale_y=scale_y,
        shift_x_px=shift_x,
        shift_y_px=shift_y,
        overlap_fraction=overlap_fraction(ref_w, ref_h, shift_x, shift_y),
        phase_peak=peak,
        phase_peak_to_median=confidence,
        reference_shape=tuple(int(v) for v in reference.shape),
        candidate_shape=tuple(int(v) for v in candidate.shape),
    )
    return registered, result


def box_blur_luma(luma: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return luma.astype(np.float32, copy=False)
    pad = int(radius)
    padded = np.pad(luma.astype(np.float32, copy=False), pad, mode="reflect")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    size = 2 * pad + 1
    total = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    return total / float(size * size)


def highpass_luma(arr: np.ndarray, radius: int = 2) -> np.ndarray:
    luma = unit_luma(arr)
    return luma - box_blur_luma(luma, radius)


def structure_metrics(reference: np.ndarray, candidate: np.ndarray, radius: int = 2) -> StructureMetrics:
    if reference.shape != candidate.shape:
        raise ValueError(f"reference and candidate shapes differ: {reference.shape} != {candidate.shape}")
    ref_hp = highpass_luma(reference, radius)
    cand_hp = highpass_luma(candidate, radius)
    diff = cand_hp - ref_hp
    highpass_rmse = float(np.sqrt(np.mean(diff * diff)))
    ref_rms = float(np.sqrt(np.mean(ref_hp * ref_hp)))
    cand_rms = float(np.sqrt(np.mean(cand_hp * cand_hp)))
    if ref_rms == 0.0:
        loss = float("inf") if highpass_rmse else 0.0
        energy_ratio = float("inf") if cand_rms else 1.0
    else:
        loss = highpass_rmse / ref_rms
        energy_ratio = cand_rms / ref_rms
    ref_flat = ref_hp.reshape(-1)
    cand_flat = cand_hp.reshape(-1)
    ref_std = float(ref_flat.std())
    cand_std = float(cand_flat.std())
    if ref_std == 0.0 or cand_std == 0.0:
        corr = 0.0
    else:
        corr = float(np.corrcoef(ref_flat, cand_flat)[0, 1])
    return StructureMetrics(
        highpass_rmse=highpass_rmse,
        highpass_reference_rms=ref_rms,
        structure_loss=float(loss),
        detail_correlation=corr,
        detail_energy_ratio=float(energy_ratio),
    )


def crop(arr: np.ndarray, spec: str | None) -> np.ndarray:
    if not spec:
        return arr
    parts = [int(part.strip()) for part in spec.split(",")]
    if len(parts) != 4:
        raise ValueError("crop must be x,y,width,height")
    x, y, width, height = parts
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("crop values must be non-negative x/y and positive width/height")
    return np.ascontiguousarray(arr[y : y + height, x : x + width])


def clipping_fraction(unit_rgb: np.ndarray, eps: float = 1e-6) -> float:
    values = np.asarray(unit_rgb, dtype=np.float64)
    return float(np.mean((values <= eps) | (values >= 1.0 - eps)))


def finite_float(value: float) -> float | str:
    if math.isfinite(value):
        return value
    return "inf"
