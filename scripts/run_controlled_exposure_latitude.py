from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "metadata/controlled_exposure_latitude_plan.json"
DEFAULT_OUTPUT = ROOT / "results/controlled_exposure_latitude"
DEFAULT_FIGURES = ROOT / "docs/figures/controlled-exposure-latitude"
DEFAULT_PUBLIC_JSON = ROOT / "metadata/controlled_exposure_latitude.json"


@dataclass
class RawFrame:
    relative_path: str
    exposure_seconds: float
    ev: float
    iso: int
    f_number: float
    exposure_compensation: float
    sequence_number: str
    timestamp: str
    focus_mode: str
    pixel_shift_info: str
    green: np.ndarray
    clipped: np.ndarray
    near_black: np.ndarray
    clipped_fraction: float
    near_black_fraction: float
    clipped_fraction_by_channel: dict[str, float]
    near_black_fraction_by_channel: dict[str, float]
    black_levels: list[int]
    white_levels: list[int]
    raw_shape: tuple[int, int]
    normalization_ev: float | None = None


def exposure_ev(exposure_seconds: float, normal_exposure_seconds: float) -> float:
    if exposure_seconds <= 0 or normal_exposure_seconds <= 0:
        raise ValueError("exposure times must be positive")
    return math.log2(exposure_seconds / normal_exposure_seconds)


def choose_white_levels(camera_white: Iterable[int | None], fallback: int) -> list[int]:
    values = [int(value or 0) for value in camera_white]
    if len(values) >= 4 and all(value > 0 for value in values[:4]):
        return values[:4]
    return [int(fallback)] * 4


def green_planes_from_mosaic(
    raw_image: np.ndarray,
    raw_pattern: np.ndarray,
    color_desc: bytes,
    black_levels: list[int],
    white_levels: list[int],
    *,
    analysis_stride: int,
    clip_headroom_codes: int,
    black_margin_codes: int,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    float,
    float,
    dict[str, float],
    dict[str, float],
]:
    if raw_pattern.shape != (2, 2):
        raise ValueError(f"only 2x2 Bayer mosaics are supported, got {raw_pattern.shape}")
    desc = color_desc.decode("ascii", errors="ignore")
    green_cells: list[tuple[int, int, int]] = []
    channel_cells: list[tuple[int, int, int, str]] = []
    label_counts: dict[str, int] = {}
    for row in range(2):
        for col in range(2):
            channel = int(raw_pattern[row, col])
            base_label = desc[channel] if channel < len(desc) else f"C{channel}"
            label_counts[base_label] = label_counts.get(base_label, 0) + 1
            suffix = label_counts[base_label] if sum(
                1 for value in raw_pattern.reshape(-1) if int(value) < len(desc) and desc[int(value)] == base_label
            ) > 1 else None
            label = f"{base_label}{suffix}" if suffix is not None else base_label
            channel_cells.append((row, col, channel, label))
            if base_label == "G":
                green_cells.append((row, col, channel))
    if len(green_cells) != 2:
        raise ValueError(f"expected two green cells in Bayer pattern, got {green_cells}")

    normalized: list[np.ndarray] = []
    clipped_masks: list[np.ndarray] = []
    black_masks: list[np.ndarray] = []
    clipped_count = 0
    near_black_count = 0
    sample_count = 0
    clipped_fraction_by_channel: dict[str, float] = {}
    near_black_fraction_by_channel: dict[str, float] = {}
    for row, col, channel, label in channel_cells:
        plane = raw_image[row::2, col::2]
        black = int(black_levels[channel])
        white = int(white_levels[channel])
        clipped_fraction_by_channel[label] = float(
            np.mean(plane >= (white - clip_headroom_codes))
        )
        near_black_fraction_by_channel[label] = float(
            np.mean(plane <= (black + black_margin_codes))
        )
    for row, col, channel in green_cells:
        plane_u16 = raw_image[row::2, col::2]
        black = int(black_levels[channel])
        white = int(white_levels[channel])
        if white <= black:
            raise ValueError(f"invalid raw range for channel {channel}: {black}..{white}")
        clipped_full = plane_u16 >= (white - clip_headroom_codes)
        near_black_full = plane_u16 <= (black + black_margin_codes)
        clipped_count += int(np.count_nonzero(clipped_full))
        near_black_count += int(np.count_nonzero(near_black_full))
        sample_count += int(plane_u16.size)

        plane = plane_u16[::analysis_stride, ::analysis_stride].astype(np.float32)
        signal = np.maximum(plane - np.float32(black), np.float32(0.0))
        normalized.append(signal / np.float32(white - black))
        clipped_masks.append(
            plane_u16[::analysis_stride, ::analysis_stride]
            >= (white - clip_headroom_codes)
        )
        black_masks.append(
            plane_u16[::analysis_stride, ::analysis_stride]
            <= (black + black_margin_codes)
        )

    green = (normalized[0] + normalized[1]) * np.float32(0.5)
    clipped = clipped_masks[0] | clipped_masks[1]
    near_black = black_masks[0] & black_masks[1]
    return (
        np.ascontiguousarray(green),
        np.ascontiguousarray(clipped),
        np.ascontiguousarray(near_black),
        clipped_count / sample_count,
        near_black_count / sample_count,
        clipped_fraction_by_channel,
        near_black_fraction_by_channel,
    )


def find_executable(explicit: Path | None, names: list[str]) -> str:
    candidates = ([str(explicit)] if explicit else []) + names
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit(f"Could not find required executable: {', '.join(names)}")


def read_exif(exiftool: str, path: Path) -> dict[str, Any]:
    command = [
        exiftool,
        "-json",
        "-n",
        "-ExposureTime",
        "-ISO",
        "-FNumber",
        "-ExposureCompensation",
        "-SequenceNumber",
        "-DateTimeOriginal",
        "-SubSecTimeOriginal",
        "-FocusMode",
        "-PixelShiftInfo",
        str(path),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"ExifTool failed for {path}")
    payload = json.loads(result.stdout)
    if not payload:
        raise RuntimeError(f"ExifTool returned no metadata for {path}")
    return payload[0]


def import_rawpy() -> Any:
    try:
        import rawpy  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "rawpy is required for sensor-domain analysis. Install with "
            "python -m pip install -e '.[raw]' or add rawpy to PYTHONPATH."
        ) from exc
    return rawpy


def decode_frame(
    rawpy: Any,
    source_root: Path,
    relative_path: str,
    metadata: dict[str, Any],
    normal_exposure_seconds: float,
    *,
    analysis_stride: int,
    clip_headroom_codes: int,
    black_margin_codes: int,
) -> RawFrame:
    path = source_root / Path(relative_path)
    with rawpy.imread(str(path)) as raw:
        black_levels = [int(value) for value in raw.black_level_per_channel]
        white_levels = choose_white_levels(
            raw.camera_white_level_per_channel,
            int(raw.white_level),
        )
        (
            green,
            clipped,
            near_black,
            clipped_fraction,
            near_black_fraction,
            clipped_fraction_by_channel,
            near_black_fraction_by_channel,
        ) = (
            green_planes_from_mosaic(
                raw.raw_image_visible,
                np.asarray(raw.raw_pattern),
                raw.color_desc,
                black_levels,
                white_levels,
                analysis_stride=analysis_stride,
                clip_headroom_codes=clip_headroom_codes,
                black_margin_codes=black_margin_codes,
            )
        )
        raw_shape = tuple(int(value) for value in raw.raw_image_visible.shape)

    exposure_seconds = float(metadata["ExposureTime"])
    subsec = str(metadata.get("SubSecTimeOriginal", ""))
    timestamp = str(metadata.get("DateTimeOriginal", ""))
    if subsec:
        timestamp = f"{timestamp}.{subsec}"
    return RawFrame(
        relative_path=relative_path,
        exposure_seconds=exposure_seconds,
        ev=exposure_ev(exposure_seconds, normal_exposure_seconds),
        iso=int(metadata.get("ISO", 0)),
        f_number=float(metadata.get("FNumber", 0.0)),
        exposure_compensation=float(metadata.get("ExposureCompensation", 0.0)),
        sequence_number=str(metadata.get("SequenceNumber", "")),
        timestamp=timestamp,
        focus_mode=str(metadata.get("FocusMode", "")),
        pixel_shift_info=str(metadata.get("PixelShiftInfo", "")),
        green=green,
        clipped=clipped,
        near_black=near_black,
        clipped_fraction=clipped_fraction,
        near_black_fraction=near_black_fraction,
        clipped_fraction_by_channel=clipped_fraction_by_channel,
        near_black_fraction_by_channel=near_black_fraction_by_channel,
        black_levels=black_levels,
        white_levels=white_levels,
        raw_shape=raw_shape,
    )


def pearson(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    av = a[mask].astype(np.float64, copy=False)
    bv = b[mask].astype(np.float64, copy=False)
    if av.size < 2:
        return 0.0
    av = av - av.mean()
    bv = bv - bv.mean()
    denom = math.sqrt(float(np.dot(av, av)) * float(np.dot(bv, bv)))
    if denom == 0.0:
        return 0.0
    return float(np.dot(av, bv) / denom)


def geometry_correlation(reference: np.ndarray, candidate: np.ndarray) -> float:
    step = max(1, min(reference.shape) // 512)
    ref = np.log1p(reference[::step, ::step] * np.float32(4096.0))
    cand = np.log1p(candidate[::step, ::step] * np.float32(4096.0))
    mask = np.isfinite(ref) & np.isfinite(cand)
    return pearson(ref, cand, mask)


def laplacian(image: np.ndarray) -> np.ndarray:
    center = image[1:-1, 1:-1]
    return (
        center * np.float32(4.0)
        - image[:-2, 1:-1]
        - image[2:, 1:-1]
        - image[1:-1, :-2]
        - image[1:-1, 2:]
    )


def make_hdr_reference(
    frames: list[RawFrame],
    *,
    exclude_path: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    weighted_sum = np.zeros(frames[0].green.shape, dtype=np.float64)
    weight_sum = np.zeros(frames[0].green.shape, dtype=np.float64)
    source_ev = np.full(frames[0].green.shape, np.nan, dtype=np.float32)
    for frame in frames:
        if frame.relative_path == exclude_path:
            continue
        normalization_ev = frame.ev if frame.normalization_ev is None else frame.normalization_ev
        normalized = frame.green / np.float32(2.0**normalization_ev)
        usable = ~frame.clipped & (frame.green > 0.0)
        weight = float(2.0**normalization_ev)
        weighted_sum[usable] += normalized[usable] * weight
        weight_sum[usable] += weight
        replace = usable & (~np.isfinite(source_ev) | (frame.ev > source_ev))
        source_ev[replace] = np.float32(frame.ev)
    hdr = np.full(frames[0].green.shape, np.nan, dtype=np.float32)
    valid = weight_sum > 0.0
    hdr[valid] = (weighted_sum[valid] / weight_sum[valid]).astype(np.float32)
    return hdr, source_ev


def band_masks(
    hdr: np.ndarray,
    *,
    inset_fraction: float = 0.08,
) -> tuple[dict[str, np.ndarray], dict[str, list[float]]]:
    if not 0.0 <= inset_fraction < 0.5:
        raise ValueError("inset_fraction must be in [0, 0.5)")
    roi = np.zeros(hdr.shape, dtype=bool)
    inset_y = int(round(hdr.shape[0] * inset_fraction))
    inset_x = int(round(hdr.shape[1] * inset_fraction))
    y_slice = slice(inset_y, hdr.shape[0] - inset_y if inset_y else None)
    x_slice = slice(inset_x, hdr.shape[1] - inset_x if inset_x else None)
    roi[y_slice, x_slice] = True
    finite = np.isfinite(hdr) & (hdr > 0.0) & roi
    values = hdr[finite]
    if values.size == 0:
        raise ValueError("HDR reference contains no valid positive values")
    percentiles = np.percentile(values, [1.0, 10.0, 35.0, 65.0, 90.0, 99.0])
    ranges = {
        "dense": [float(percentiles[0]), float(percentiles[1])],
        "midtone": [float(percentiles[2]), float(percentiles[3])],
        "thin": [float(percentiles[4]), float(percentiles[5])],
    }
    masks = {
        name: finite & (hdr >= low) & (hdr <= high)
        for name, (low, high) in ranges.items()
    }
    return masks, ranges


def measured_response_ev(frame: RawFrame, normal: RawFrame) -> float:
    usable = (
        ~frame.clipped
        & ~normal.clipped
        & (frame.green > 0.002)
        & (normal.green > 0.002)
        & (frame.green < 0.75)
        & (normal.green < 0.75)
    )
    if np.count_nonzero(usable) < 100:
        return float("nan")
    ratios = frame.green[usable] / normal.green[usable]
    return float(np.median(np.log2(ratios)))


def pixel_shift_active(value: str) -> bool:
    text = value.strip().lower()
    if text in ("", "n/a"):
        return False
    fields = text.split()
    return not (
        len(fields) >= 3
        and fields[0].strip("0") == ""
        and fields[1] == "0"
        and fields[2] == "0"
    )


def frame_band_metrics(
    frame: RawFrame,
    hdr: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, dict[str, float]]:
    normalization_ev = frame.ev if frame.normalization_ev is None else frame.normalization_ev
    normalized = frame.green / np.float32(2.0**normalization_ev)
    hdr_hp = laplacian(hdr)
    frame_hp = laplacian(normalized)
    result: dict[str, dict[str, float]] = {}
    for name, mask in masks.items():
        valid_mask = mask & np.isfinite(hdr)
        count = int(np.count_nonzero(valid_mask))
        if count == 0:
            raise ValueError(f"empty signal band: {name}")
        ref = hdr[valid_mask]
        cand = normalized[valid_mask]
        delta = cand - ref
        scale = max(float(np.median(ref)), 1e-12)
        relative_rmse = float(np.sqrt(np.mean(delta * delta)) / scale)
        relative_mae = float(np.mean(np.abs(delta)) / scale)
        relative_p95 = float(np.percentile(np.abs(delta) / np.maximum(ref, 1e-12), 95.0))
        inner_mask = (
            valid_mask[1:-1, 1:-1]
            & np.isfinite(hdr_hp)
            & np.isfinite(frame_hp)
        )
        structure_correlation = pearson(hdr_hp, frame_hp, inner_mask)
        result[name] = {
            "pixel_count": count,
            "relative_rmse": relative_rmse,
            "relative_mae": relative_mae,
            "relative_p95_error": relative_p95,
            "recovery_db": float(-20.0 * math.log10(max(relative_rmse, 1e-12))),
            "structure_correlation": structure_correlation,
            "clipped_fraction": float(np.mean(frame.clipped[valid_mask])),
            "near_black_fraction": float(np.mean(frame.near_black[valid_mask])),
        }
    return result


def public_frame(
    frame: RawFrame,
    normal: RawFrame,
    frames: list[RawFrame],
    masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    hdr, _ = make_hdr_reference(frames, exclude_path=frame.relative_path)
    measured_ev = frame.ev if frame.normalization_ev is None else frame.normalization_ev
    normalized = frame.green / np.float32(2.0**measured_ev)
    geometry = geometry_correlation(hdr, normalized)
    return {
        "file": frame.relative_path,
        "exposure_seconds": frame.exposure_seconds,
        "computed_ev": frame.ev,
        "camera_exposure_compensation": frame.exposure_compensation,
        "measured_response_ev": measured_ev,
        "linearity_error_ev": measured_ev - frame.ev if math.isfinite(measured_ev) else None,
        "iso": frame.iso,
        "f_number": frame.f_number,
        "sequence_number": frame.sequence_number,
        "timestamp": frame.timestamp,
        "focus_mode": frame.focus_mode,
        "pixel_shift_info": frame.pixel_shift_info,
        "raw_shape": list(frame.raw_shape),
        "black_levels": frame.black_levels,
        "white_levels": frame.white_levels,
        "green_clipped_fraction": frame.clipped_fraction,
        "green_near_black_fraction": frame.near_black_fraction,
        "clipped_fraction_by_channel": frame.clipped_fraction_by_channel,
        "near_black_fraction_by_channel": frame.near_black_fraction_by_channel,
        "geometry_correlation_to_hdr": geometry,
        "bands": frame_band_metrics(frame, hdr, masks),
    }


def evaluate_case(
    rawpy: Any,
    exiftool: str,
    source_root: Path,
    case: dict[str, Any],
    *,
    analysis_stride: int,
    clip_headroom_codes: int,
    black_margin_codes: int,
    analysis_inset_fraction: float,
) -> dict[str, Any]:
    relative_files = [str(value) for value in case["files"]]
    normal_path = str(case["normal"])
    if normal_path not in relative_files:
        raise ValueError(f"normal file is not part of case {case['key']}: {normal_path}")
    for relative in relative_files:
        if not (source_root / relative).is_file():
            raise FileNotFoundError(source_root / relative)

    metadata = {
        relative: read_exif(exiftool, source_root / relative)
        for relative in relative_files
    }
    normal_exposure = float(metadata[normal_path]["ExposureTime"])
    frames = [
        decode_frame(
            rawpy,
            source_root,
            relative,
            metadata[relative],
            normal_exposure,
            analysis_stride=analysis_stride,
            clip_headroom_codes=clip_headroom_codes,
            black_margin_codes=black_margin_codes,
        )
        for relative in relative_files
    ]
    normal = next(frame for frame in frames if frame.relative_path == normal_path)
    if len({frame.iso for frame in frames}) != 1:
        raise ValueError(f"ISO changed inside case {case['key']}")
    if any(pixel_shift_active(frame.pixel_shift_info) for frame in frames):
        raise ValueError(f"Pixel Shift frame found inside case {case['key']}")
    if len({frame.raw_shape for frame in frames}) != 1:
        raise ValueError(f"raw geometry changed inside case {case['key']}")

    for frame in frames:
        response_ev = measured_response_ev(frame, normal)
        frame.normalization_ev = response_ev if math.isfinite(response_ev) else frame.ev

    hdr, source_ev = make_hdr_reference(frames)
    masks, ranges = band_masks(hdr, inset_fraction=analysis_inset_fraction)
    public_frames = [public_frame(frame, normal, frames, masks) for frame in frames]
    best_by_band: dict[str, dict[str, Any]] = {}
    normal_public = next(item for item in public_frames if item["file"] == normal_path)
    for band in ("dense", "midtone", "thin"):
        best = min(public_frames, key=lambda item: item["bands"][band]["relative_rmse"])
        normal_rmse = float(normal_public["bands"][band]["relative_rmse"])
        best_rmse = float(best["bands"][band]["relative_rmse"])
        best_by_band[band] = {
            "file": best["file"],
            "computed_ev": best["computed_ev"],
            "relative_rmse": best_rmse,
            "normal_relative_rmse": normal_rmse,
            "normal_to_best_improvement": normal_rmse / max(best_rmse, 1e-12),
        }

    source_values = source_ev[np.isfinite(source_ev)]
    all_frames_clipped = np.logical_and.reduce([frame.clipped for frame in frames])
    all_frames_near_black = np.logical_and.reduce([frame.near_black for frame in frames])
    return {
        "key": str(case["key"]),
        "label": str(case["label"]),
        "normal": normal_path,
        "capture_count": len(frames),
        "iso": normal.iso,
        "f_number_recorded": normal.f_number,
        "analysis_grid_shape": list(hdr.shape),
        "hdr_valid_fraction": float(np.mean(np.isfinite(hdr))),
        "all_frames_clipped_fraction": float(np.mean(all_frames_clipped)),
        "all_frames_near_black_fraction": float(np.mean(all_frames_near_black)),
        "signal_band_ranges_normal_equivalent": ranges,
        "hdr_source_ev_distribution": {
            "median": float(np.median(source_values)),
            "p05": float(np.percentile(source_values, 5.0)),
            "p95": float(np.percentile(source_values, 95.0)),
        },
        "best_by_band": best_by_band,
        "frames": public_frames,
    }


def finite_values(payload: list[dict[str, Any]], key: str) -> list[float]:
    values = [float(item[key]) for item in payload if item.get(key) is not None]
    return [value for value in values if math.isfinite(value)]


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    linearity = [
        frame
        for case in cases
        for frame in case["frames"]
        if frame["linearity_error_ev"] is not None
    ]
    errors = [abs(value) for value in finite_values(linearity, "linearity_error_ev")]
    normal_rows = [
        next(frame for frame in case["frames"] if frame["file"] == case["normal"])
        for case in cases
    ]
    dense_improvements = [
        float(case["best_by_band"]["dense"]["normal_to_best_improvement"])
        for case in cases
    ]
    thin_improvements = [
        float(case["best_by_band"]["thin"]["normal_to_best_improvement"])
        for case in cases
    ]
    return {
        "case_count": len(cases),
        "frame_count": sum(int(case["capture_count"]) for case in cases),
        "median_absolute_linearity_error_ev": float(np.median(errors)),
        "max_absolute_linearity_error_ev": float(np.max(errors)),
        "median_normal_green_clipped_fraction": float(
            np.median([row["green_clipped_fraction"] for row in normal_rows])
        ),
        "max_normal_green_clipped_fraction": float(
            np.max([row["green_clipped_fraction"] for row in normal_rows])
        ),
        "max_all_frames_clipped_fraction": float(
            np.max([case["all_frames_clipped_fraction"] for case in cases])
        ),
        "median_dense_normal_to_best_improvement": float(np.median(dense_improvements)),
        "median_thin_normal_to_best_improvement": float(np.median(thin_improvements)),
        "best_dense_ev_by_case": {
            case["key"]: case["best_by_band"]["dense"]["computed_ev"] for case in cases
        },
        "best_thin_ev_by_case": {
            case["key"]: case["best_by_band"]["thin"]["computed_ev"] for case in cases
        },
    }


def write_csv(cases: list[dict[str, Any]], path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for case in cases:
        for frame in case["frames"]:
            row = {
                "case": case["key"],
                "label": case["label"],
                "file": frame["file"],
                "exposure_seconds": frame["exposure_seconds"],
                "computed_ev": frame["computed_ev"],
                "measured_response_ev": frame["measured_response_ev"],
                "linearity_error_ev": frame["linearity_error_ev"],
                "iso": frame["iso"],
                "green_clipped_fraction": frame["green_clipped_fraction"],
                "green_near_black_fraction": frame["green_near_black_fraction"],
                "geometry_correlation_to_hdr": frame["geometry_correlation_to_hdr"],
            }
            for band in ("dense", "midtone", "thin"):
                for metric, value in frame["bands"][band].items():
                    row[f"{band}_{metric}"] = value
            rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


COLORS = {
    "church": "#2563eb",
    "dinner": "#dc2626",
    "christmas": "#16a34a",
    "white-shirt": "#9333ea",
    "dense": "#1d4ed8",
    "midtone": "#64748b",
    "thin": "#dc2626",
}


def svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def svg_chart(
    title: str,
    subtitle: str,
    series: list[dict[str, Any]],
    *,
    y_label: str,
    y_min: float,
    y_max: float,
    y_ticks: list[float],
    log_y: bool = False,
) -> str:
    width, height = 980, 600
    left, right, top, bottom = 92, 32, 82, 74
    plot_w, plot_h = width - left - right, height - top - bottom
    all_x = [float(x) for item in series for x, _ in item["points"]]
    x_min, x_max = min(all_x), max(all_x)
    x_pad = max(0.5, (x_max - x_min) * 0.05)
    x_min -= x_pad
    x_max += x_pad

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        if log_y:
            lo = math.log10(y_min)
            hi = math.log10(y_max)
            value = math.log10(max(value, y_min))
        else:
            lo, hi = y_min, y_max
        return top + (hi - value) / (hi - lo) * plot_h

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="34" font-family="system-ui,sans-serif" font-size="24" font-weight="700" fill="#0f172a">{svg_escape(title)}</text>',
        f'<text x="{left}" y="58" font-family="system-ui,sans-serif" font-size="14" fill="#475569">{svg_escape(subtitle)}</text>',
    ]
    for tick in y_ticks:
        y = sy(tick)
        out.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e2e8f0"/>')
        label = f"{tick:g}"
        out.append(f'<text x="{left - 12}" y="{y + 5:.2f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="12" fill="#475569">{label}</text>')
    x_start = math.ceil(x_min)
    x_end = math.floor(x_max)
    for tick in range(x_start, x_end + 1):
        x = sx(float(tick))
        out.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_h}" stroke="#f1f5f9"/>')
        out.append(f'<text x="{x:.2f}" y="{top + plot_h + 24}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="12" fill="#475569">{tick:+d}</text>')
    out.extend(
        [
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#334155"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#334155"/>',
            f'<text x="{left + plot_w / 2:.2f}" y="{height - 22}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" fill="#334155">Exposure relative to normal (EV)</text>',
            f'<text x="22" y="{top + plot_h / 2:.2f}" transform="rotate(-90 22 {top + plot_h / 2:.2f})" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" fill="#334155">{svg_escape(y_label)}</text>',
        ]
    )
    legend_x = left + 10
    for index, item in enumerate(series):
        color = item["color"]
        points = [(sx(float(x)), sy(float(y))) for x, y in item["points"]]
        path = " ".join(("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}" for i, (x, y) in enumerate(points))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for x, y in points:
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}" stroke="#fff" stroke-width="1.5"/>')
        lx = legend_x + (index % 3) * 260
        ly = top + 20 + (index // 3) * 22
        out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 22}" y2="{ly}" stroke="{color}" stroke-width="3"/>')
        out.append(f'<text x="{lx + 30}" y="{ly + 4}" font-family="system-ui,sans-serif" font-size="12" fill="#0f172a">{svg_escape(item["label"])}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_figures(cases: list[dict[str, Any]], figure_dir: Path) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    clipping_series = []
    for case in cases:
        clipping_series.append(
            {
                "label": case["label"],
                "color": COLORS.get(case["key"], "#334155"),
                "points": [
                    (frame["computed_ev"], max(frame["green_clipped_fraction"], 1e-7))
                    for frame in sorted(case["frames"], key=lambda item: item["computed_ev"])
                ],
            }
        )
    (figure_dir / "sensor-clipping.svg").write_text(
        svg_chart(
            "Sensor clipping across the exposure brackets",
            "Green-site samples within 64 raw codes of the measured channel white level.",
            clipping_series,
            y_label="Clipped green fraction",
            y_min=1e-7,
            y_max=1.0,
            y_ticks=[1e-7, 1e-5, 1e-3, 1e-1, 1.0],
            log_y=True,
        ),
        encoding="utf-8",
    )

    for case in cases:
        series = []
        for band in ("dense", "midtone", "thin"):
            series.append(
                {
                    "label": band.capitalize(),
                    "color": COLORS[band],
                    "points": [
                        (frame["computed_ev"], max(frame["bands"][band]["relative_rmse"], 1e-4))
                        for frame in sorted(case["frames"], key=lambda item: item["computed_ev"])
                    ],
                }
            )
        (figure_dir / f"{case['key']}-hdr-reference-error.svg").write_text(
            svg_chart(
                f"{case['label']}: recovery error by signal band",
                "Raw green signal normalized to the normal exposure and compared with the bracket HDR reference.",
                series,
                y_label="Relative RMSE",
                y_min=1e-3,
                y_max=10.0,
                y_ticks=[1e-3, 1e-2, 1e-1, 1.0, 10.0],
                log_y=True,
            ),
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure controlled exposure latitude directly in Bayer raw samples."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--public-json", type=Path, default=DEFAULT_PUBLIC_JSON)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--exiftool", type=Path, default=None)
    parser.add_argument("--analysis-stride", type=int, default=1)
    parser.add_argument("--clip-headroom-codes", type=int, default=64)
    parser.add_argument("--black-margin-codes", type=int, default=16)
    parser.add_argument("--analysis-inset-fraction", type=float, default=0.08)
    args = parser.parse_args()

    if args.analysis_stride < 1:
        raise SystemExit("--analysis-stride must be at least 1")
    source_root = args.source_root.resolve()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    exiftool = find_executable(
        args.exiftool,
        ["exiftool.exe", "exiftool", r"C:\Program Files\ExifTool\ExifTool.exe"],
    )
    rawpy = import_rawpy()
    cases = [
        evaluate_case(
            rawpy,
            exiftool,
            source_root,
            case,
            analysis_stride=args.analysis_stride,
            clip_headroom_codes=args.clip_headroom_codes,
            black_margin_codes=args.black_margin_codes,
            analysis_inset_fraction=args.analysis_inset_fraction,
        )
        for case in plan["cases"]
    ]
    summary = summarize(cases)
    payload = {
        "schema_version": 1,
        "scope": (
            "Four complete single-shot ARW exposure brackets, measured directly in "
            "black-subtracted Bayer green samples without demosaic or tone mapping."
        ),
        "method": {
            "normalization": "Raw green samples are divided by channel range and a robust median midtone response EV relative to the declared normal frame; reported shutter-time EV remains a separate linearity audit.",
            "hdr_reference": "Per pixel, non-clipped bracket samples are exposure-weighted in normal-equivalent raw space; each tested frame is scored against a leave-one-out reference that excludes that frame.",
            "bands": "Dense, midtone, and thin bands are HDR-reference percentiles 1-10, 35-65, and 90-99.",
            "clipping": f"A green sample is clipped within {args.clip_headroom_codes} raw codes of the camera channel white level.",
            "near_black": f"A green sample is near black within {args.black_margin_codes} raw codes of its channel black level.",
            "analysis_stride": args.analysis_stride,
            "analysis_inset_fraction": args.analysis_inset_fraction,
        },
        "summary": summary,
        "cases": cases,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    local_json = args.output_dir / "metrics.json"
    local_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_csv(cases, args.output_dir / "metrics.csv")
    args.public_json.parent.mkdir(parents=True, exist_ok=True)
    args.public_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_figures(cases, args.figure_dir)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {local_json}")
    print(f"Wrote {args.public_json}")
    print(f"Wrote figures under {args.figure_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
