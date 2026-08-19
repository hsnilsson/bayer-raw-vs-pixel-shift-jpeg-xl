from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import subprocess
import struct
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from color_patch_metrics import (  # noqa: E402
    color_space_names,
    patch_metric_rows,
    summarize_patch_metric_rows,
)
from run_public_latitude_stress import build_transforms, metrics  # noqa: E402


DEFAULT_OUT_DIR = ROOT / "results/dng_jxl_verification"

ADC_LEVELS = {
    "lossless": "lossless",
    "d003": "d003",
    "d005": "d005",
    "d010": "d010",
}

PANEL_TRANSFORMS = {
    "identity",
    "negative_density_print",
    "negative_density_hard_print",
    "negative_density_shadow_print",
}

PANEL_CROPS = {"center", "upper-left", "lower-right"}


@dataclass(frozen=True)
class Frame:
    stem: str
    label: str
    source: Path


@dataclass(frozen=True)
class MainImage:
    page: Any
    shape: tuple[int, int, int]
    crop_origin: tuple[int, int]
    crop_size: tuple[int, int]
    white_level: tuple[float, float, float]


@dataclass(frozen=True)
class CropWindow:
    name: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class RasterWindow:
    x: int
    y: int
    width: int
    height: int


def add_local_optional_deps() -> None:
    candidates = []
    env_path = os.environ.get("JXL_PYDEPS")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(r"C:\tmp\jxl_pydeps"))
    for path in reversed(candidates):
        if path.is_dir():
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)


def import_tifffile():
    add_local_optional_deps()
    try:
        import tifffile  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "This script needs tifffile and imagecodecs with DNG/JPEG XL support. "
            "Install the optional dependencies or set JXL_PYDEPS to a directory "
            "containing tifffile, imagecodecs, and numpy."
        ) from exc
    return tifffile


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def capture_command(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": args, "error": str(exc)}
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def tool_versions() -> dict[str, Any]:
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": {
            "numpy": np.__version__,
            "Pillow": package_version("Pillow"),
            "tifffile": package_version("tifffile"),
            "imagecodecs": package_version("imagecodecs"),
        },
        "tools": {
            "git": capture_command(["git", "--version"]),
        },
    }


def scalar(value: Any) -> Any:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator)
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, int) for v in value):
        denominator = value[1] or 1
        return float(value[0]) / float(denominator)
    return value


def tag_value(page: Any, name: str, default: Any = None) -> Any:
    tag = page.tags.get(name)
    if tag is None:
        return default
    return tag.value


def tag_tuple(page: Any, name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    value = tag_value(page, name)
    if value is None:
        return default
    if isinstance(value, (tuple, list)):
        return tuple(float(scalar(item)) for item in value)
    return (float(scalar(value)),)


def tag_int_tuple(page: Any, name: str, default: tuple[int, int]) -> tuple[int, int]:
    value = tag_value(page, name)
    if value is None:
        return default
    if isinstance(value, (tuple, list)):
        if len(value) == 4 and all(isinstance(item, int) for item in value):
            first_denominator = value[1] or 1
            second_denominator = value[3] or 1
            return (
                int(round(value[0] / first_denominator)),
                int(round(value[2] / second_denominator)),
            )
        parsed = [float(scalar(item)) for item in value]
        if len(parsed) >= 2:
            return (int(round(parsed[0])), int(round(parsed[1])))
    return default


def parse_opcode_list2(data: bytes | None) -> list[dict[str, Any]]:
    if not data:
        return []
    if len(data) < 4:
        raise ValueError("OpcodeList2 is too short")
    pos = 0
    opcode_count = struct.unpack(">I", data[pos : pos + 4])[0]
    pos += 4
    opcodes: list[dict[str, Any]] = []
    for _ in range(opcode_count):
        if pos + 16 > len(data):
            raise ValueError("OpcodeList2 ended inside opcode header")
        opcode_id, dng_version, flags, byte_count = struct.unpack(">IIII", data[pos : pos + 16])
        pos += 16
        payload = data[pos : pos + byte_count]
        if len(payload) != byte_count:
            raise ValueError("OpcodeList2 ended inside opcode payload")
        pos += byte_count
        item: dict[str, Any] = {
            "opcode_id": opcode_id,
            "dng_version": dng_version,
            "flags": flags,
            "byte_count": byte_count,
        }
        if opcode_id == 8:
            if byte_count < 36:
                raise ValueError("MapPolynomial payload is too short")
            (
                top,
                left,
                bottom,
                right,
                plane,
                planes,
                row_pitch,
                col_pitch,
                degree,
            ) = struct.unpack(">iiiiiiiii", payload[:36])
            coefficient_count = degree + 1
            expected = 36 + coefficient_count * 8
            if byte_count != expected:
                raise ValueError(
                    f"MapPolynomial payload length {byte_count} does not match degree {degree}"
                )
            coefficients = [
                struct.unpack(">d", payload[36 + index * 8 : 44 + index * 8])[0]
                for index in range(coefficient_count)
            ]
            item.update(
                {
                    "name": "MapPolynomial",
                    "top": top,
                    "left": left,
                    "bottom": bottom,
                    "right": right,
                    "plane": plane,
                    "planes": planes,
                    "row_pitch": row_pitch,
                    "col_pitch": col_pitch,
                    "degree": degree,
                    "coefficients": coefficients,
                }
            )
        else:
            item["name"] = f"Opcode{opcode_id}"
            item["payload_hex"] = payload.hex()
        opcodes.append(item)
    if pos != len(data):
        raise ValueError("OpcodeList2 has trailing bytes")
    return opcodes


def apply_map_polynomial(
    values: np.ndarray,
    opcode: dict[str, Any],
    raster_window: RasterWindow,
) -> None:
    top = int(opcode["top"])
    left = int(opcode["left"])
    bottom = int(opcode["bottom"])
    right = int(opcode["right"])
    overlap_left = max(left, raster_window.x)
    overlap_top = max(top, raster_window.y)
    overlap_right = min(right, raster_window.x + raster_window.width)
    overlap_bottom = min(bottom, raster_window.y + raster_window.height)
    if overlap_left >= overlap_right or overlap_top >= overlap_bottom:
        return

    row_pitch = max(1, int(opcode["row_pitch"]))
    col_pitch = max(1, int(opcode["col_pitch"]))
    y0 = overlap_top - raster_window.y
    y1 = overlap_bottom - raster_window.y
    x0 = overlap_left - raster_window.x
    x1 = overlap_right - raster_window.x
    if row_pitch != 1:
        offset = (overlap_top - top) % row_pitch
        y0 += (row_pitch - offset) % row_pitch
    if col_pitch != 1:
        offset = (overlap_left - left) % col_pitch
        x0 += (col_pitch - offset) % col_pitch

    plane = int(opcode["plane"])
    planes = int(opcode["planes"])
    coefficients = [float(value) for value in opcode["coefficients"]]
    for channel in range(plane, min(plane + planes, values.shape[2])):
        source = values[y0:y1:row_pitch, x0:x1:col_pitch, channel]
        result = np.zeros_like(source, dtype=np.float32)
        for coefficient in reversed(coefficients):
            result = result * source + coefficient
        values[y0:y1:row_pitch, x0:x1:col_pitch, channel] = np.clip(result, 0.0, 1.0)


def apply_opcode_list2(
    values: np.ndarray,
    opcodes: list[dict[str, Any]],
    raster_window: RasterWindow,
) -> np.ndarray:
    if not opcodes:
        return values
    result = values.copy()
    for opcode in opcodes:
        if opcode.get("name") != "MapPolynomial":
            raise ValueError(f"unsupported OpcodeList2 opcode: {opcode.get('name')}")
        apply_map_polynomial(result, opcode, raster_window)
        np.clip(result, 0.0, 1.0, out=result)
    return result


def find_main_image(tif: Any) -> MainImage:
    candidates: list[tuple[int, Any]] = []
    for series in tif.series:
        if len(series.shape) != 3:
            continue
        if int(series.shape[2]) < 3:
            continue
        if str(series.dtype) != "uint16":
            continue
        pixels = int(series.shape[0]) * int(series.shape[1])
        candidates.append((pixels, series.pages[0]))
    if not candidates:
        raise ValueError("no uint16 RGB main image series found")
    _, page = max(candidates, key=lambda item: item[0])
    height, width, channels = (int(v) for v in page.shape[:3])
    crop_origin = tag_int_tuple(page, "DefaultCropOrigin", (0, 0))
    crop_size = tag_int_tuple(page, "DefaultCropSize", (width - crop_origin[0], height - crop_origin[1]))
    crop_width = max(0, min(crop_size[0], width - crop_origin[0]))
    crop_height = max(0, min(crop_size[1], height - crop_origin[1]))
    white_level = tag_tuple(page, "WhiteLevel", (65535.0, 65535.0, 65535.0))
    if len(white_level) == 1:
        white_level = (white_level[0], white_level[0], white_level[0])
    if len(white_level) < 3:
        white_level = tuple(list(white_level) + [white_level[-1]] * (3 - len(white_level)))
    return MainImage(
        page=page,
        shape=(height, width, channels),
        crop_origin=crop_origin,
        crop_size=(crop_width, crop_height),
        white_level=tuple(float(v) for v in white_level[:3]),
    )


def dng_metadata(path: Path) -> dict[str, Any]:
    tifffile = import_tifffile()
    with tifffile.TiffFile(path) as tif:
        main = find_main_image(tif)
        page = main.page
        first = tif.pages[0]
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "dng_version": tag_value(first, "DNGVersion"),
            "dng_backward_version": tag_value(first, "DNGBackwardVersion"),
            "shape": list(main.shape),
            "active_crop_origin": list(main.crop_origin),
            "active_crop_size": list(main.crop_size),
            "compression": int(page.compression),
            "compression_name": getattr(page.compression, "name", str(page.compression)),
            "photometric": int(page.photometric),
            "photometric_name": getattr(page.photometric, "name", str(page.photometric)),
            "bits_per_sample": list(page.bitspersample)
            if isinstance(page.bitspersample, tuple)
            else page.bitspersample,
            "white_level": list(main.white_level),
            "is_tiled": bool(page.is_tiled),
            "tile_width": int(page.tilewidth),
            "tile_length": int(page.tilelength),
            "segments": len(page.dataoffsets),
            "jxl_distance": tag_value(page, "JXLDistance"),
            "jxl_effort": tag_value(page, "JXLEffort"),
            "jxl_decode_speed": tag_value(page, "JXLDecodeSpeed"),
            "opcode_list2": parse_opcode_list2(tag_value(page, "OpcodeList2")),
        }


def frame_from_source_spec(scan_root: Path, spec: str) -> Frame:
    if "=" in spec:
        source_text, label = spec.split("=", 1)
    else:
        source_text = spec
        label = ""

    candidate = Path(source_text)
    if candidate.suffix.lower() == ".dng":
        source = candidate if candidate.is_absolute() else scan_root / candidate
        stem = source.stem
    else:
        stem = source_text
        source = scan_root / f"{stem}.dng"
    if not label:
        label = stem
    return Frame(stem=stem, label=label, source=source)


def discover_frames(scan_root: Path, requested: list[str] | None, levels: list[str]) -> list[Frame]:
    if requested:
        discovered = [frame_from_source_spec(scan_root, spec) for spec in requested]
    else:
        discover_level = levels[0]
        candidate_dir = scan_root / "adc_jxl_dng" / ADC_LEVELS[discover_level]
        if not candidate_dir.is_dir():
            raise SystemExit(
                "No --source values were provided and the candidate discovery "
                f"directory does not exist: {candidate_dir}"
            )
        discovered = [
            Frame(stem=path.stem, label=path.stem, source=scan_root / path.name)
            for path in sorted(candidate_dir.glob("*.dng"))
        ]

    frames: list[Frame] = []
    for frame in discovered:
        if not frame.source.is_file():
            raise SystemExit(f"missing source DNG: {frame.source}")
        frames.append(frame)
    return frames


def choose_windows(active_size: tuple[int, int], crop_size: int) -> list[CropWindow]:
    active_width, active_height = active_size
    size = max(1, min(crop_size, active_width, active_height))
    positions = [
        ("center", (active_width - size) // 2, (active_height - size) // 2),
        ("upper-left", 0, 0),
        ("upper-right", active_width - size, 0),
        ("lower-left", 0, active_height - size),
        ("lower-right", active_width - size, active_height - size),
    ]
    seen: set[tuple[int, int, int, int]] = set()
    windows: list[CropWindow] = []
    for name, x, y in positions:
        rect = (x, y, size, size)
        if rect in seen:
            continue
        seen.add(rect)
        windows.append(CropWindow(name=name, x=x, y=y, width=size, height=size))
    return windows


def raster_rect(main: MainImage, window: CropWindow) -> tuple[int, int, int, int]:
    return (
        main.crop_origin[0] + window.x,
        main.crop_origin[1] + window.y,
        window.width,
        window.height,
    )


def extract_windows(
    path: Path,
    windows: list[CropWindow],
    maxworkers: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    tifffile = import_tifffile()
    with tifffile.TiffFile(path) as tif:
        main = find_main_image(tif)
        page = main.page
        raster_height, raster_width = main.shape[:2]
        wanted = {window.name: raster_rect(main, window) for window in windows}
        output = {
            window.name: np.zeros((window.height, window.width, 3), dtype=np.uint16)
            for window in windows
        }
        filled = {window.name: 0 for window in windows}
        total = {window.name: window.width * window.height for window in windows}

        for data, indices, _shape in page.segments(sort=True, maxworkers=maxworkers):
            tile = np.asarray(data)
            if tile.ndim == 4 and tile.shape[0] == 1:
                tile = tile[0]
            if tile.ndim != 3 or tile.shape[2] < 3:
                continue
            tile_y = int(indices[-3])
            tile_x = int(indices[-2])
            tile_height = min(int(tile.shape[0]), raster_height - tile_y)
            tile_width = min(int(tile.shape[1]), raster_width - tile_x)
            tile = tile[:tile_height, :tile_width, :3]
            if tile.dtype.byteorder == ">":
                tile = tile.astype(np.uint16)

            tile_x1 = tile_x + tile_width
            tile_y1 = tile_y + tile_height
            for name, (x, y, width, height) in wanted.items():
                x1 = x + width
                y1 = y + height
                overlap_x0 = max(x, tile_x)
                overlap_y0 = max(y, tile_y)
                overlap_x1 = min(x1, tile_x1)
                overlap_y1 = min(y1, tile_y1)
                if overlap_x0 >= overlap_x1 or overlap_y0 >= overlap_y1:
                    continue
                src_x0 = overlap_x0 - tile_x
                src_y0 = overlap_y0 - tile_y
                dst_x0 = overlap_x0 - x
                dst_y0 = overlap_y0 - y
                rows = overlap_y1 - overlap_y0
                cols = overlap_x1 - overlap_x0
                output[name][dst_y0 : dst_y0 + rows, dst_x0 : dst_x0 + cols] = tile[
                    src_y0 : src_y0 + rows,
                    src_x0 : src_x0 + cols,
                ]
                filled[name] += rows * cols

            if all(filled[name] >= total[name] for name in filled):
                break

        missing = [name for name, count in filled.items() if count != total[name]]
        if missing:
            raise RuntimeError(f"incomplete DNG window extraction from {path}: {missing}")
        meta = {
            "shape": list(main.shape),
            "active_crop_origin": list(main.crop_origin),
            "active_crop_size": list(main.crop_size),
            "white_level": list(main.white_level),
            "opcode_list2": parse_opcode_list2(tag_value(page, "OpcodeList2")),
        }
        return output, meta


def to_comparable_uint16(
    arr: np.ndarray,
    white_level: tuple[float, float, float],
    opcodes: list[dict[str, Any]] | None = None,
    raster_window: RasterWindow | None = None,
) -> np.ndarray:
    white = np.maximum(np.array(white_level, dtype=np.float32), 1.0)
    unit = arr.astype(np.float32) / white.reshape(1, 1, 3)
    if opcodes:
        if raster_window is None:
            raise ValueError("raster_window is required when applying OpcodeList2")
        unit = apply_opcode_list2(unit, opcodes, raster_window)
    return np.round(np.clip(unit, 0.0, 1.0) * 65535.0).astype(np.uint16)


def raw_exact_metrics(source: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    diff = candidate.astype(np.int32) - source.astype(np.int32)
    abs_diff = np.abs(diff)
    return {
        "raw_exact": bool(np.array_equal(source, candidate)),
        "raw_max_error": int(abs_diff.max(initial=0)),
        "raw_mae": float(abs_diff.mean()),
    }


def to_uint8(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    return np.round(np.clip(values, 0.0, 1.0) * 255).astype(np.uint8)


def resize(arr: np.ndarray, size: int) -> Image.Image:
    image = Image.fromarray(arr)
    if image.width > size or image.height > size:
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
    return image


def abs_diff_panel(ref: np.ndarray, cand: np.ndarray, gain: float) -> np.ndarray:
    diff = np.abs(cand - ref) * gain
    mono = np.clip(diff.mean(axis=2, keepdims=True), 0.0, 1.0)
    return to_uint8(np.repeat(mono, 3, axis=2))


def signed_diff_panel(ref: np.ndarray, cand: np.ndarray, gain: float) -> np.ndarray:
    diff = np.clip((cand - ref) * gain, -1.0, 1.0)
    positive = np.clip(diff, 0.0, 1.0).mean(axis=2)
    negative = np.clip(-diff, 0.0, 1.0).mean(axis=2)
    panel = np.zeros((*positive.shape, 3), dtype=np.float32)
    panel[:, :, 0] = negative
    panel[:, :, 1] = positive
    panel[:, :, 2] = negative
    return to_uint8(panel)


def draw_label(image: Image.Image, text: str) -> Image.Image:
    labelled = Image.new("RGB", (image.width, image.height + 28), "white")
    labelled.paste(image, (0, 28))
    draw = ImageDraw.Draw(labelled)
    draw.rectangle((0, 0, image.width, 28), fill=(248, 248, 248))
    draw.text((8, 7), text, fill=(20, 20, 20))
    return labelled


def write_panel(
    output: Path,
    ref_t: np.ndarray,
    cand_t: np.ndarray,
    title: str,
    candidate_label: str,
    panel_size: int,
    diff_gain: float,
) -> None:
    pieces = [
        draw_label(resize(to_uint8(ref_t), panel_size), "reference"),
        draw_label(resize(to_uint8(cand_t), panel_size), candidate_label),
        draw_label(resize(abs_diff_panel(ref_t, cand_t, diff_gain), panel_size), f"abs diff x{diff_gain:g}"),
        draw_label(resize(signed_diff_panel(ref_t, cand_t, diff_gain), panel_size), f"signed diff x{diff_gain:g}"),
    ]
    gutter = 10
    width = sum(piece.width for piece in pieces) + gutter * (len(pieces) - 1)
    height = max(piece.height for piece in pieces) + 48
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    draw.text((8, 8), title, fill=(0, 0, 0))
    x = 0
    for piece in pieces:
        panel.paste(piece, (x, 48))
        x += piece.width + gutter
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.save(output)


def safe_float(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return str(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return list(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["level"]), str(row["transform"]))
        groups.setdefault(key, []).append(row)
    summary: list[dict[str, Any]] = []
    for (level, transform), group in sorted(groups.items()):
        summary.append(
            {
                "level": level,
                "transform": transform,
                "rows": len(group),
                "mean_mae_16bit": float(np.mean([float(row["mae_16bit"]) for row in group])),
                "worst_mae_16bit": float(max(float(row["mae_16bit"]) for row in group)),
                "worst_max_error_16bit": int(max(int(row["max_error_16bit"]) for row in group)),
                "worst_p99_pixel_max_error_16bit": float(
                    max(float(row["p99_pixel_max_error_16bit"]) for row in group)
                ),
                "mean_psnr_db": float(np.mean([float(row["psnr_db"]) for row in group if not math.isinf(float(row["psnr_db"]))]))
                if any(not math.isinf(float(row["psnr_db"])) for row in group)
                else float("inf"),
            }
        )
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: safe_float(value) for key, value in row.items()})


def write_markdown_summary(
    out_dir: Path,
    frames: list[Frame],
    levels: list[str],
    metadata_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    patch_summary_rows: list[dict[str, Any]],
    panel_paths: list[Path],
) -> None:
    lines = [
        "# DNG/JXL Verification",
        "",
        "Private local result. Do not publish image panels without replacing the scan material.",
        "",
        "## Inputs",
        "",
    ]
    for frame in frames:
        lines.append(f"- `{frame.stem}`: {frame.label}")
    lines.extend(["", "## ADC Levels", ""])
    for level in levels:
        lines.append(f"- `{level}`")
    lines.extend(["", "## Size Ratios", ""])
    lines.append("| Frame | Level | Source MiB | Candidate MiB | Candidate % |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for row in metadata_rows:
        lines.append(
            f"| `{row['stem']}` | `{row['level']}` | "
            f"{float(row['source_mib']):.2f} | {float(row['candidate_mib']):.2f} | "
            f"{float(row['candidate_percent']):.1f}% |"
        )
    lines.extend(["", "## Metric Summary", ""])
    lines.append("| Level | Transform | Rows | Mean MAE | Worst MAE | Worst max error | Worst p99 pixel max | Mean PSNR |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in summary_rows:
        psnr = "inf" if math.isinf(float(row["mean_psnr_db"])) else f"{float(row['mean_psnr_db']):.2f}"
        lines.append(
            f"| `{row['level']}` | `{row['transform']}` | {row['rows']} | "
            f"{float(row['mean_mae_16bit']):.2f} | {float(row['worst_mae_16bit']):.2f} | "
            f"{int(row['worst_max_error_16bit'])} | {float(row['worst_p99_pixel_max_error_16bit']):.1f} | "
            f"{psnr} |"
        )
    if patch_summary_rows:
        lines.extend(["", "## Color Patch Summary", ""])
        lines.append(
            "DeltaE00 is computed after averaging each patch in the declared linear RGB comparison "
            "space, then converting the patch mean to Lab. These values compare candidate and "
            "reference behavior in a controlled pipeline; they are not an absolute colorimetric "
            "truth claim about the original film scene."
        )
        lines.extend(["", "| Level | Transform | Patches | Median DeltaE00 | Mean DeltaE00 | P95 DeltaE00 | Max DeltaE00 | Mean abs bias | Mean RGB RMSE | Median err/ref std |"])
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for row in patch_summary_rows:
            err_ref_std = (
                "inf"
                if math.isinf(float(row["median_error_to_ref_luma_std"]))
                else f"{float(row['median_error_to_ref_luma_std']):.3f}"
            )
            lines.append(
                f"| `{row['level']}` | `{row['transform']}` | {row['patches']} | "
                f"{float(row['median_delta_e00']):.4f} | {float(row['mean_delta_e00']):.4f} | "
                f"{float(row['p95_delta_e00']):.4f} | {float(row['max_delta_e00']):.4f} | "
                f"{float(row['mean_abs_bias_16bit']):.2f} | {float(row['mean_error_rgb_rmse_16bit']):.2f} | "
                f"{err_ref_std} |"
            )
    if panel_paths:
        lines.extend(["", "## Panels", ""])
        for path in panel_paths:
            relative = path.relative_to(out_dir).as_posix()
            lines.append(f"- [{relative}]({relative})")
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def candidate_path(scan_root: Path, level: str, stem: str) -> Path:
    return scan_root / "adc_jxl_dng" / ADC_LEVELS[level] / f"{stem}.dng"


def analyze(args: argparse.Namespace) -> int:
    scan_root = Path(args.scan_root)
    out_dir = Path(args.out_dir)
    levels = args.level or list(ADC_LEVELS)
    invalid = sorted(set(levels) - set(ADC_LEVELS))
    if invalid:
        raise SystemExit(f"unknown ADC level(s): {', '.join(invalid)}")
    frames = discover_frames(scan_root, args.source, levels)

    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_by_path: dict[Path, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    panel_paths: list[Path] = []

    for frame in frames:
        print(f"Frame {frame.stem}: {frame.label}", flush=True)
        source_meta = dng_metadata(frame.source)
        metadata_by_path[frame.source] = source_meta
        active_size = tuple(int(v) for v in source_meta["active_crop_size"])
        windows = choose_windows(active_size, args.crop_size)
        source_crops, source_extract_meta = extract_windows(frame.source, windows, args.maxworkers)
        source_white = tuple(float(v) for v in source_extract_meta["white_level"])
        source_origin = tuple(int(v) for v in source_extract_meta["active_crop_origin"])
        source_opcodes = list(source_extract_meta["opcode_list2"])
        source_unit = {
            window.name: to_comparable_uint16(
                source_crops[window.name],
                source_white,
                source_opcodes,
                RasterWindow(
                    x=source_origin[0] + window.x,
                    y=source_origin[1] + window.y,
                    width=window.width,
                    height=window.height,
                ),
            )
            for window in windows
        }

        for level in levels:
            cand = candidate_path(scan_root, level, frame.stem)
            if not cand.is_file():
                raise SystemExit(f"missing candidate DNG: {cand}")
            print(f"  Level {level}", flush=True)
            cand_meta = dng_metadata(cand)
            metadata_by_path[cand] = cand_meta
            cand_crops, cand_extract_meta = extract_windows(cand, windows, args.maxworkers)
            cand_white = tuple(float(v) for v in cand_extract_meta["white_level"])
            cand_origin = tuple(int(v) for v in cand_extract_meta["active_crop_origin"])
            cand_opcodes = list(cand_extract_meta["opcode_list2"])
            cand_unit = {
                window.name: to_comparable_uint16(
                    cand_crops[window.name],
                    cand_white,
                    cand_opcodes,
                    RasterWindow(
                        x=cand_origin[0] + window.x,
                        y=cand_origin[1] + window.y,
                        width=window.width,
                        height=window.height,
                    ),
                )
                for window in windows
            }
            source_mib = frame.source.stat().st_size / 1024 / 1024
            cand_mib = cand.stat().st_size / 1024 / 1024
            metadata_rows.append(
                {
                    "stem": frame.stem,
                    "label": frame.label,
                    "level": level,
                    "source_mib": source_mib,
                    "candidate_mib": cand_mib,
                    "candidate_percent": cand_mib / source_mib * 100.0,
                    "source_shape": "x".join(str(v) for v in source_meta["shape"]),
                    "candidate_shape": "x".join(str(v) for v in cand_meta["shape"]),
                    "source_crop": "x".join(str(v) for v in source_meta["active_crop_size"]),
                    "candidate_crop": "x".join(str(v) for v in cand_meta["active_crop_size"]),
                    "source_white_level": " ".join(str(v) for v in source_white),
                    "candidate_white_level": " ".join(str(v) for v in cand_white),
                    "candidate_opcode_list2": "+".join(
                        str(opcode.get("name", opcode.get("opcode_id"))) for opcode in cand_opcodes
                    ),
                    "jxl_distance": cand_meta.get("jxl_distance"),
                    "jxl_effort": cand_meta.get("jxl_effort"),
                }
            )

            for window in windows:
                raw_compare: dict[str, Any] = {"raw_exact": "", "raw_max_error": "", "raw_mae": ""}
                if source_white == cand_white and source_crops[window.name].shape == cand_crops[window.name].shape:
                    raw_compare = raw_exact_metrics(source_crops[window.name], cand_crops[window.name])
                transforms = build_transforms(source_unit[window.name])
                for transform in transforms:
                    ref_t = transform.apply(source_unit[window.name])
                    cand_t = transform.apply(cand_unit[window.name])
                    row: dict[str, Any] = {
                        "stem": frame.stem,
                        "label": frame.label,
                        "level": level,
                        "crop": window.name,
                        "crop_width": window.width,
                        "crop_height": window.height,
                        "source_white_level": " ".join(str(v) for v in source_white),
                        "candidate_white_level": " ".join(str(v) for v in cand_white),
                        "size_percent": cand_mib / source_mib * 100.0,
                        "transform": transform.name,
                    }
                    row.update(raw_compare)
                    row.update(metrics(ref_t, cand_t))
                    all_rows.append(row)

                    if args.patch_metrics:
                        patch_context = {
                            "stem": frame.stem,
                            "label": frame.label,
                            "level": level,
                            "crop": window.name,
                            "crop_width": window.width,
                            "crop_height": window.height,
                            "size_percent": cand_mib / source_mib * 100.0,
                            "transform": transform.name,
                            "patch_size": args.patch_size,
                        }
                        for patch_row in patch_metric_rows(
                            ref_t,
                            cand_t,
                            patch_size=args.patch_size,
                            rgb_space=args.patch_color_space,
                        ):
                            combined = patch_context.copy()
                            combined.update(patch_row)
                            patch_rows.append(combined)

                    panel_levels = set(args.panel_level or levels)
                    panel_crops = set(args.panel_crop or PANEL_CROPS)
                    panel_transforms = set(args.panel_transform or PANEL_TRANSFORMS)
                    should_panel = (
                        args.panels
                        and level in panel_levels
                        and transform.name in panel_transforms
                        and window.name in panel_crops
                    )
                    if should_panel:
                        panel_path = (
                            out_dir
                            / "panels"
                            / frame.stem
                            / f"{level}_{window.name}_{transform.name}.png"
                        )
                        title = (
                            f"{frame.label} | {level} | {window.name} | {transform.name} | "
                            f"MAE {float(row['mae_16bit']):.2f}"
                        )
                        write_panel(
                            panel_path,
                            ref_t,
                            cand_t,
                            title,
                            f"ADC {level}",
                            args.panel_size,
                            args.diff_gain,
                        )
                        panel_paths.append(panel_path)

        del source_crops
        del source_unit

    summary_rows = summarize(all_rows)
    patch_summary_rows = summarize_patch_metric_rows(patch_rows) if patch_rows else []
    patch_luminance_rows = (
        summarize_patch_metric_rows(patch_rows, ("level", "transform", "luminance_bin"))
        if patch_rows
        else []
    )
    patch_chroma_rows = (
        summarize_patch_metric_rows(patch_rows, ("level", "transform", "chroma_bin"))
        if patch_rows
        else []
    )
    write_csv(out_dir / "metrics.csv", all_rows)
    write_csv(out_dir / "patch_metrics.csv", patch_rows)
    write_csv(out_dir / "metadata.csv", metadata_rows)
    write_csv(out_dir / "summary.csv", summary_rows)
    write_csv(out_dir / "patch_summary.csv", patch_summary_rows)
    write_csv(out_dir / "patch_luminance_summary.csv", patch_luminance_rows)
    write_csv(out_dir / "patch_chroma_summary.csv", patch_chroma_rows)
    (out_dir / "metrics.json").write_text(json.dumps(json_safe(all_rows), indent=2), encoding="utf-8")
    if args.patch_json:
        (out_dir / "patch_metrics.json").write_text(
            json.dumps(json_safe(patch_rows), indent=2),
            encoding="utf-8",
        )
    (out_dir / "metadata.json").write_text(
        json.dumps(
            json_safe(
                {
                    "scan_root": str(scan_root),
                    "frames": [frame.__dict__ | {"source": str(frame.source)} for frame in frames],
                    "files": {str(path): meta for path, meta in metadata_by_path.items()},
                    "tool_versions": tool_versions(),
                    "parameters": {
                        "levels": levels,
                        "crop_size": args.crop_size,
                        "maxworkers": args.maxworkers,
                        "panels": args.panels,
                        "panel_levels": args.panel_level,
                        "panel_crops": args.panel_crop,
                        "panel_transforms": args.panel_transform,
                        "panel_size": args.panel_size,
                        "diff_gain": args.diff_gain,
                        "patch_metrics": args.patch_metrics,
                        "patch_size": args.patch_size,
                        "patch_color_space": args.patch_color_space,
                        "patch_json": args.patch_json,
                    },
                }
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    write_markdown_summary(
        out_dir,
        frames,
        levels,
        metadata_rows,
        summary_rows,
        patch_summary_rows,
        panel_paths,
    )
    print(f"Wrote {out_dir / 'SUMMARY.md'}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare source DNG files with Adobe DNG Converter DNG/JXL variants "
            "through matched active-crop windows."
        )
    )
    parser.add_argument(
        "--scan-root",
        type=Path,
        required=True,
        help="Directory containing source DNG files and adc_jxl_dng/<level>/ candidate folders.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Source stem, DNG filename/path, or STEM=label. Repeatable. "
            "Defaults to source stems discovered from the first selected ADC level."
        ),
    )
    parser.add_argument(
        "--level",
        action="append",
        choices=sorted(ADC_LEVELS),
        help="ADC level to analyze; repeatable. Defaults to all levels.",
    )
    parser.add_argument("--crop-size", type=int, default=1536)
    parser.add_argument("--maxworkers", type=int, default=4)
    parser.add_argument(
        "--no-patch-metrics",
        dest="patch_metrics",
        action="store_false",
        help="Disable patch-based mean-color DeltaE00 and patch noise diagnostics.",
    )
    parser.set_defaults(patch_metrics=True)
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument(
        "--patch-color-space",
        choices=color_space_names(),
        default="srgb",
        help=(
            "Declared linear RGB comparison space used for patch mean RGB -> XYZ -> Lab. "
            "Defaults to srgb."
        ),
    )
    parser.add_argument(
        "--patch-json",
        action="store_true",
        help="Also write full patch_metrics.json. CSV is written by default and is much smaller.",
    )
    parser.add_argument("--panels", action="store_true")
    parser.add_argument(
        "--panel-level",
        action="append",
        choices=sorted(ADC_LEVELS),
        help="ADC level to render panels for; repeatable. Defaults to all analyzed levels.",
    )
    parser.add_argument(
        "--panel-crop",
        action="append",
        choices=["center", "upper-left", "upper-right", "lower-left", "lower-right"],
        help="Crop window to render panels for; repeatable. Defaults to a small selected set.",
    )
    parser.add_argument(
        "--panel-transform",
        action="append",
        help="Transform to render panels for; repeatable. Defaults to selected negative/identity transforms.",
    )
    parser.add_argument("--panel-size", type=int, default=512)
    parser.add_argument("--diff-gain", type=float, default=64.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.crop_size <= 0:
        raise SystemExit("--crop-size must be positive")
    if args.maxworkers <= 0:
        raise SystemExit("--maxworkers must be positive")
    if args.patch_size <= 0:
        raise SystemExit("--patch-size must be positive")
    return analyze(args)


if __name__ == "__main__":
    raise SystemExit(main())
