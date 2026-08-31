from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CJXL = ROOT / "work/jxl-tools/bin/cjxl.exe"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"


def import_tifffile():
    try:
        import tifffile  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "This script needs tifffile. Install it with:\n"
            '  python -m pip install -e ".[tiff]"'
        ) from exc
    return tifffile


def run(args: list[str], cwd: Path = ROOT) -> None:
    print("$ " + " ".join(str(a) for a in args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def find_tool(name: str, fallback: Path) -> str:
    found = shutil.which(name)
    if found:
        return found
    if fallback.exists():
        return str(fallback)
    raise SystemExit(f"could not find {name}; install libjxl tools or place them under {fallback.parent}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(path: Path) -> str:
    text = path.stem.lower()
    safe = []
    for char in text:
        safe.append(char if char.isalnum() else "-")
    return "-".join("".join(safe).split("-"))[:80] or "image"


def read_tiff(path: Path) -> tuple[np.ndarray, bytes | None]:
    tifffile = import_tifffile()
    try:
        arr = tifffile.memmap(path)
    except Exception:
        arr = tifffile.imread(path)
    with tifffile.TiffFile(path) as tif:
        profile_tag = tif.pages[0].tags.get("InterColorProfile")
        icc = bytes(profile_tag.value) if profile_tag is not None else None

    source_was_grayscale = arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim != 3:
        raise ValueError(f"unsupported image shape {arr.shape} in {path}")
    if arr.shape[2] > 3:
        arr = arr[:, :, :3]
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    if arr.dtype.byteorder == ">":
        arr = arr.astype(arr.dtype.newbyteorder("="), copy=False)
    if arr.dtype not in (np.uint8, np.uint16):
        arr = normalize_to_uint16(arr)
    if source_was_grayscale:
        icc = None
    return arr, icc


def normalize_to_uint16(arr: np.ndarray) -> np.ndarray:
    values = arr.astype(np.float64)
    values -= values.min(initial=0)
    max_value = values.max(initial=0)
    if max_value > 0:
        values /= max_value
    return np.round(values * 65535).astype(np.uint16)


def crop_image(arr: np.ndarray, crop_size: int, crop: str) -> np.ndarray:
    height, width = arr.shape[:2]
    size = min(crop_size, height, width)
    if crop == "center":
        x0 = (width - size) // 2
        y0 = (height - size) // 2
    elif crop == "upper-left":
        x0 = 0
        y0 = 0
    elif crop == "lower-right":
        x0 = width - size
        y0 = height - size
    else:
        raise ValueError(f"unknown crop mode {crop}")
    return np.ascontiguousarray(arr[y0 : y0 + size, x0 : x0 + size, :3])


def write_ppm(path: Path, arr: np.ndarray) -> int:
    if arr.dtype == np.uint8:
        max_value = 255
        payload = arr.tobytes()
    elif arr.dtype == np.uint16:
        max_value = 65535
        payload = arr.astype(">u2", copy=False).tobytes()
    else:
        raise ValueError(f"unsupported PPM dtype {arr.dtype}")

    height, width = arr.shape[:2]
    header = f"P6\n{width} {height}\n{max_value}\n".encode("ascii")
    path.write_bytes(header + payload)
    return max_value


def read_png(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"not a PNG file: {path}")
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if None in (width, height, bit_depth, color_type, interlace):
        raise ValueError(f"missing PNG header: {path}")
    if interlace != 0:
        raise ValueError("interlaced PNG is not supported")
    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    channels = channels_by_type[color_type]
    bytes_per_sample = bit_depth // 8
    bytes_per_pixel = channels * bytes_per_sample
    stride = width * bytes_per_pixel
    raw = zlib.decompress(bytes(idat))
    recon = bytearray(height * stride)
    previous = bytes(stride)
    pos = out = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scanline = bytearray(raw[pos : pos + stride])
        pos += stride
        for i in range(stride):
            left = scanline[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            up = previous[i]
            upper_left = previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            if filter_type == 1:
                scanline[i] = (scanline[i] + left) & 0xFF
            elif filter_type == 2:
                scanline[i] = (scanline[i] + up) & 0xFF
            elif filter_type == 3:
                scanline[i] = (scanline[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                scanline[i] = (scanline[i] + paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"unsupported PNG filter {filter_type}")
        recon[out : out + stride] = scanline
        previous = bytes(scanline)
        out += stride
    dtype = np.uint8 if bit_depth == 8 else ">u2"
    arr = np.frombuffer(bytes(recon), dtype=dtype).reshape((height, width, channels))
    if bit_depth == 16:
        arr = arr.astype(np.uint16)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    return np.ascontiguousarray(arr[:, :, :3])


def paeth(left: int, up: int, upper_left: int) -> int:
    p = left + up - upper_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - upper_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return upper_left


def to_unit(arr: np.ndarray) -> np.ndarray:
    peak = 65535.0 if arr.dtype == np.uint16 else 255.0
    return arr.astype(np.float32) / peak


def metrics(ref: np.ndarray, cand: np.ndarray, peak: float = 65535.0) -> dict[str, float | int]:
    diff = (cand.astype(np.float64) - ref.astype(np.float64)) * peak
    abs_diff = np.abs(diff)
    mse = float(np.mean(diff * diff))
    rmse = math.sqrt(mse)
    return {
        "max_error_16bit": int(np.round(abs_diff.max(initial=0))),
        "mae_16bit": float(abs_diff.mean()),
        "rmse_16bit": rmse,
        "psnr_db": float("inf") if mse == 0 else 20 * math.log10(65535.0 / rmse),
        "p99_pixel_max_error_16bit": float(np.percentile(abs_diff.max(axis=2), 99)),
    }


@dataclass
class Transform:
    name: str
    apply: Callable[[np.ndarray], np.ndarray]
    label: str = ""
    description: str = ""


def build_transforms(reference: np.ndarray) -> list[Transform]:
    ref = to_unit(reference)
    inv_ref = 1.0 - ref
    inv_low = np.percentile(inv_ref, 0.5, axis=(0, 1))
    inv_high = np.percentile(inv_ref, 99.5, axis=(0, 1))
    inv_span = np.maximum(inv_high - inv_low, 1e-6)

    ref_linear = np.power(np.clip(ref, 0.0, 1.0), 2.2)
    base = np.percentile(ref_linear, 99.7, axis=(0, 1))
    black = np.percentile(ref_linear, 0.3, axis=(0, 1))
    trans_ref = np.clip((ref_linear - black) / np.maximum(base - black, 1e-6), 1e-5, 1.0)
    density_ref = -np.log(trans_ref)
    density_low = np.percentile(density_ref, 0.5, axis=(0, 1))
    density_high = np.percentile(density_ref, 99.5, axis=(0, 1))
    density_span = np.maximum(density_high - density_low, 1e-6)
    reference_luma = (
        ref_linear[:, :, 0] * 0.2126
        + ref_linear[:, :, 1] * 0.7152
        + ref_linear[:, :, 2] * 0.0722
    )
    shadow_white = max(float(np.percentile(reference_luma, 12.0)), 1e-6)
    highlight_black = float(np.percentile(reference_luma, 88.0))
    highlight_white = max(float(np.percentile(reference_luma, 99.8)), highlight_black + 1e-6)

    def density_positive(arr: np.ndarray) -> np.ndarray:
        x = np.power(np.clip(to_unit(arr), 0.0, 1.0), 2.2)
        trans = np.clip((x - black) / np.maximum(base - black, 1e-6), 1e-5, 1.0)
        density = -np.log(trans)
        y = np.clip((density - density_low) / density_span, 0.0, 1.0)
        return y

    def normalized_logistic(x: np.ndarray, contrast: float, midpoint: float) -> np.ndarray:
        y = 1.0 / (1.0 + np.exp(-contrast * (x - midpoint)))
        lo = 1.0 / (1.0 + math.exp(contrast * midpoint))
        hi = 1.0 / (1.0 + math.exp(-contrast * (1.0 - midpoint)))
        return np.clip((y - lo) / (hi - lo), 0.0, 1.0)

    def identity(arr: np.ndarray) -> np.ndarray:
        return to_unit(arr)

    def shadow_push(arr: np.ndarray) -> np.ndarray:
        x = to_unit(arr)
        lifted = np.clip(x * 8.0, 0.0, 1.0)
        return np.power(lifted, 1 / 2.2)

    def shadow_recovery(arr: np.ndarray) -> np.ndarray:
        """Expand the lower reference luminance range in a shared linear scale."""
        linear = np.power(np.clip(to_unit(arr), 0.0, 1.0), 2.2)
        return np.power(np.clip(linear / shadow_white, 0.0, 1.0), 1 / 2.2)

    def highlight_separation(arr: np.ndarray) -> np.ndarray:
        """Expand the upper reference luminance range with the same channel mapping."""
        linear = np.power(np.clip(to_unit(arr), 0.0, 1.0), 2.2)
        expanded = (linear - highlight_black) / (highlight_white - highlight_black)
        return np.power(np.clip(expanded, 0.0, 1.0), 1 / 2.2)

    def steep_curve(arr: np.ndarray) -> np.ndarray:
        x = to_unit(arr)
        y = 1.0 / (1.0 + np.exp(-9.0 * (x - 0.5)))
        lo = 1.0 / (1.0 + math.exp(4.5))
        hi = 1.0 / (1.0 + math.exp(-4.5))
        return np.clip((y - lo) / (hi - lo), 0.0, 1.0)

    def negative_stretch(arr: np.ndarray) -> np.ndarray:
        x = 1.0 - to_unit(arr)
        y = np.clip((x - inv_low) / inv_span, 0.0, 1.0)
        return np.power(y, 1 / 2.2)

    def negative_grade(arr: np.ndarray) -> np.ndarray:
        y = negative_stretch(arr)
        y = np.clip(y * np.array([1.12, 1.0, 0.92], dtype=np.float32), 0.0, 1.0)
        y = 1.0 / (1.0 + np.exp(-7.0 * (y - 0.48)))
        return np.clip(y, 0.0, 1.0)

    def negative_density_print(arr: np.ndarray) -> np.ndarray:
        y = density_positive(arr)
        y = np.power(np.clip(y, 0.0, 1.0), 0.85)
        y = normalized_logistic(y, contrast=6.5, midpoint=0.47)
        return np.clip(y, 0.0, 1.0)

    def negative_density_hard_print(arr: np.ndarray) -> np.ndarray:
        y = density_positive(arr)
        y = np.clip((y - 0.035) / 0.90, 0.0, 1.0)
        y = np.clip(y * np.array([1.07, 1.0, 0.94], dtype=np.float32), 0.0, 1.0)
        y = normalized_logistic(y, contrast=9.0, midpoint=0.50)
        return np.clip(y, 0.0, 1.0)

    def negative_density_hard_shadow_recovery(arr: np.ndarray) -> np.ndarray:
        """Apply the hard density inversion, then lift its lower positive values."""
        y = density_positive(arr)
        y = np.clip((y - 0.035) / 0.90, 0.0, 1.0)
        y = np.power(y, 0.68)
        y = np.clip(y * np.array([1.07, 1.0, 0.94], dtype=np.float32), 0.0, 1.0)
        y = normalized_logistic(y, contrast=9.0, midpoint=0.50)
        return np.clip(y, 0.0, 1.0)

    def negative_density_shadow_print(arr: np.ndarray) -> np.ndarray:
        y = density_positive(arr)
        y = np.clip((y - 0.015) / 0.86, 0.0, 1.0)
        y = np.power(y, 0.68)
        y = normalized_logistic(y, contrast=7.5, midpoint=0.42)
        return np.clip(y, 0.0, 1.0)

    return [
        Transform("identity", identity, "Normal", "Unmodified display of the rendered crop."),
        Transform("shadow_push_plus3stops", shadow_push, "Legacy shadow push", "Legacy diagnostic transform."),
        Transform(
            "shadow_recovery_luma_p12",
            shadow_recovery,
            "Shadow recovery",
            "Expands the reference crop's darkest 12% of linear luminance across the display range. "
            "A deliberately strong edit-resilience check, not a recommended grade.",
        ),
        Transform("steep_curve", steep_curve, "Legacy steep curve", "Legacy diagnostic transform."),
        Transform(
            "highlight_separation_luma_p88_p998",
            highlight_separation,
            "Highlight separation",
            "Expands the reference crop's 88th to 99.8th percentile of linear luminance. "
            "A deliberately strong edit-resilience check, not a recommended grade.",
        ),
        Transform("negative_percentile_stretch", negative_stretch, "Negative percentile stretch", "Negative display diagnostic."),
        Transform("negative_grade", negative_grade, "Negative grade", "Negative display diagnostic."),
        Transform("negative_density_print", negative_density_print, "Negative density print", "Negative-density display diagnostic."),
        Transform(
            "negative_density_hard_print",
            negative_density_hard_print,
            "Hard negative-density inversion",
            "Maps reference-normalized RGB transmission to density, then a positive image; clips 3.5%/10%, "
            "applies a small fixed channel balance and strong contrast. A reproducible stress proxy, not a film-specific inversion.",
        ),
        Transform(
            "negative_density_hard_shadow_recovery",
            negative_density_hard_shadow_recovery,
            "Hard inversion + shadow recovery",
            "Uses the same hard density inversion, then lifts its lower positive values before the final hard contrast. "
            "A compound edit-resilience stress check, not a recommended film grade.",
        ),
        Transform("negative_density_shadow_print", negative_density_shadow_print, "Negative shadow print", "Negative display diagnostic."),
    ]


def encode_decode(
    reference_ppm: Path,
    encoded: Path,
    decoded: Path,
    distance: str,
    effort: str,
    cjxl: str,
    djxl: str,
    icc: Path | None,
) -> None:
    cmd = [cjxl, str(reference_ppm), str(encoded), "-d", distance, "-e", effort]
    if icc is not None:
        cmd.extend(["-x", f"icc_pathname={icc}"])
    run(cmd)
    run([djxl, str(encoded), str(decoded)])


def analyze_one(path: Path, args: argparse.Namespace) -> list[dict[str, object]]:
    cjxl = find_tool("cjxl", DEFAULT_CJXL)
    djxl = find_tool("djxl", DEFAULT_DJXL)
    out_root = Path(args.out_dir)
    image_id = slugify(path)
    image_dir = out_root / image_id
    image_dir.mkdir(parents=True, exist_ok=True)

    arr, icc_bytes = read_tiff(path)
    crop = crop_image(arr, args.crop_size, args.crop)
    ppm = image_dir / "reference.ppm"
    peak = write_ppm(ppm, crop)
    icc_path = None
    if icc_bytes:
        icc_path = image_dir / "reference.icc"
        icc_path.write_bytes(icc_bytes)

    transforms = build_transforms(crop)
    rows: list[dict[str, object]] = []
    for distance in args.distance:
        encoded = image_dir / f"jxl_d{distance.replace('.', '_')}.jxl"
        decoded = image_dir / f"jxl_d{distance.replace('.', '_')}.png"
        encode_decode(ppm, encoded, decoded, distance, args.effort, cjxl, djxl, icc_path)
        candidate = read_png(decoded)
        if candidate.dtype != crop.dtype:
            if crop.dtype == np.uint16 and candidate.dtype == np.uint8:
                candidate = (candidate.astype(np.uint16) * 257).astype(np.uint16)
            elif crop.dtype == np.uint8 and candidate.dtype == np.uint16:
                candidate = (candidate / 257).round().astype(np.uint8)
        for transform in transforms:
            ref_t = transform.apply(crop)
            cand_t = transform.apply(candidate)
            row: dict[str, object] = {
                "image": str(path),
                "image_id": image_id,
                "source_sha256": sha256(path),
                "crop": args.crop,
                "crop_size": crop.shape[0],
                "source_dtype": str(crop.dtype),
                "source_peak": peak,
                "distance": distance,
                "encoded": str(encoded),
                "encoded_bytes": encoded.stat().st_size,
                "transform": transform.name,
            }
            row.update(metrics(ref_t, cand_t))
            rows.append(row)
            print(
                f"{image_id} d={distance} {transform.name}: "
                f"MAE={row['mae_16bit']:.2f} PSNR={row['psnr_db']:.2f} "
                f"p99={row['p99_pixel_max_error_16bit']:.1f}"
            )

    (image_dir / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def write_reports(rows: list[dict[str, object]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "metrics.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a public JPEG XL latitude stress test on TIFF images.")
    parser.add_argument("inputs", nargs="+", type=Path, help="input TIFF images")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/public_latitude_stress")
    parser.add_argument(
        "--distance",
        action="append",
        default=None,
        help="JPEG XL distance; repeatable. Defaults to 0.03, 0.05, and 0.10.",
    )
    parser.add_argument("--effort", default="7")
    parser.add_argument("--crop-size", type=int, default=2048)
    parser.add_argument("--crop", choices=["center", "upper-left", "lower-right"], default="center")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.distance is None:
        args.distance = ["0.03", "0.05", "0.10"]
    rows: list[dict[str, object]] = []
    for path in args.inputs:
        rows.extend(analyze_one(path, args))
    write_reports(rows, Path(args.out_dir))
    print(f"Wrote {Path(args.out_dir) / 'metrics.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
