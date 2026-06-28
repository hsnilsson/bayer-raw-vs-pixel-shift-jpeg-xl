#!/usr/bin/env python3
"""
Compare JPEG XL/TIFF/JPEG encodes and rendered DNG files against one reference.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps


@dataclass
class Candidate:
    name: str
    path: Path
    encoded_path: Path | None = None
    butteraugli: float | None = None


def find_exe(name: str, override: str | None = None) -> str | None:
    if override:
        return override
    return shutil.which(name)


def run_cmd(args: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("$ " + " ".join(quote_arg(a) for a in args))
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)


def quote_arg(value: str) -> str:
    if any(c.isspace() for c in value):
        return f'"{value}"'
    return value


def load_image(path: Path) -> tuple[np.ndarray, int]:
    if path.suffix.lower() == ".png":
        arr = read_png(path)
        return normalize_array(arr)
    if path.suffix.lower() in (".tif", ".tiff"):
        arr = try_read_tiff(path)
        if arr is not None:
            return normalize_array(arr)

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA", "I;16", "I;16B", "I;16L"):
            im = im.convert("RGB")
        arr = np.asarray(im)

    return normalize_array(arr)


def normalize_array(arr: np.ndarray) -> tuple[np.ndarray, int]:
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]

    if arr.dtype.byteorder == ">":
        arr = arr.astype(arr.dtype.newbyteorder("="), copy=False)

    if arr.dtype == np.uint16:
        peak = 65535
    elif arr.dtype == np.uint8:
        peak = 255
    else:
        arr = arr.astype(np.float64)
        peak = 1 if arr.max(initial=0) <= 1 else 65535

    return arr, peak


def try_read_tiff(path: Path) -> np.ndarray | None:
    try:
        import tifffile  # type: ignore
    except ModuleNotFoundError:
        return None
    return tifffile.imread(path)


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
        raise ValueError("interlaced PNG is not supported by the built-in reader")
    if bit_depth not in (8, 16):
        raise ValueError(f"unsupported PNG bit depth {bit_depth}; use 8 or 16")

    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    if color_type not in channels_by_type:
        raise ValueError(f"unsupported PNG color type {color_type}; use grayscale/RGB/RGBA")

    channels = channels_by_type[color_type]
    bytes_per_sample = bit_depth // 8
    bytes_per_pixel = channels * bytes_per_sample
    stride = width * bytes_per_pixel
    raw = zlib.decompress(bytes(idat))
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(f"unexpected PNG data length in {path}: got {len(raw)}, expected {expected}")

    recon = bytearray(height * stride)
    src = 0
    for row in range(height):
        filter_type = raw[src]
        src += 1
        cur = bytearray(raw[src : src + stride])
        src += stride
        prior_start = (row - 1) * stride
        out_start = row * stride
        for i in range(stride):
            left = recon[out_start + i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            up = recon[prior_start + i] if row else 0
            up_left = recon[prior_start + i - bytes_per_pixel] if row and i >= bytes_per_pixel else 0
            if filter_type == 0:
                value = cur[i]
            elif filter_type == 1:
                value = cur[i] + left
            elif filter_type == 2:
                value = cur[i] + up
            elif filter_type == 3:
                value = cur[i] + ((left + up) // 2)
            elif filter_type == 4:
                value = cur[i] + paeth(left, up, up_left)
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}")
            recon[out_start + i] = value & 0xFF

    dtype = np.dtype(">u2") if bit_depth == 16 else np.dtype("u1")
    arr = np.frombuffer(bytes(recon), dtype=dtype).reshape((height, width, channels))
    if color_type == 4:
        arr = arr[:, :, :1]
    return arr


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def align_to_reference(ref: np.ndarray, cand: np.ndarray) -> np.ndarray:
    if ref.shape != cand.shape:
        raise ValueError(f"shape mismatch: reference {ref.shape}, candidate {cand.shape}")
    if cand.dtype == ref.dtype:
        return cand
    if ref.dtype == np.uint16 and cand.dtype == np.uint8:
        return (cand.astype(np.uint16) * 257).astype(np.uint16)
    if ref.dtype == np.uint8 and cand.dtype == np.uint16:
        return np.round(cand.astype(np.float64) / 257).astype(np.uint8)
    return cand.astype(ref.dtype, copy=False)


def compute_metrics(ref: np.ndarray, cand: np.ndarray, peak: int) -> dict[str, float | int | bool]:
    ref_f = ref.astype(np.float64)
    cand_f = cand.astype(np.float64)
    diff = cand_f - ref_f
    abs_diff = np.abs(diff)
    mse = float(np.mean(diff * diff))
    rmse = math.sqrt(mse)
    psnr = float("inf") if mse == 0 else 20 * math.log10(peak / rmse)
    max_error = int(abs_diff.max(initial=0))
    mae = float(abs_diff.mean())
    ssim = global_ssim(ref_f, cand_f, peak)
    return {
        "exact": bool(max_error == 0),
        "mae": mae,
        "rmse": rmse,
        "psnr_db": psnr,
        "max_error": max_error,
        "ssim": ssim,
        "dssim": (1 - ssim) / 2,
    }


def global_ssim(a: np.ndarray, b: np.ndarray, peak: int) -> float:
    c1 = (0.01 * peak) ** 2
    c2 = (0.03 * peak) ** 2
    scores = []
    for ch in range(a.shape[2]):
        x = a[:, :, ch]
        y = b[:, :, ch]
        mux = float(x.mean())
        muy = float(y.mean())
        sigx = float(((x - mux) ** 2).mean())
        sigy = float(((y - muy) ** 2).mean())
        sigxy = float(((x - mux) * (y - muy)).mean())
        score = ((2 * mux * muy + c1) * (2 * sigxy + c2)) / ((mux * mux + muy * muy + c1) * (sigx + sigy + c2))
        scores.append(score)
    return float(np.mean(scores))


def as_preview(arr: np.ndarray) -> Image.Image:
    if arr.dtype == np.uint16:
        out = np.round(arr.astype(np.float64) / 257).clip(0, 255).astype(np.uint8)
    elif arr.dtype == np.uint8:
        out = arr
    else:
        maxv = arr.max(initial=1)
        out = np.round(arr / maxv * 255).clip(0, 255).astype(np.uint8)
    if out.shape[2] == 1:
        return Image.fromarray(out[:, :, 0], "L")
    return Image.fromarray(out[:, :, :3], "RGB")


def save_crops(ref: np.ndarray, cand: np.ndarray, out_dir: Path, name: str, crops: list[tuple[int, int, int, int]], scale: int) -> None:
    crop_dir = out_dir / "crops" / safe_name(name)
    crop_dir.mkdir(parents=True, exist_ok=True)
    diff = np.abs(cand.astype(np.float64) - ref.astype(np.float64))
    diff_peak = diff.max(initial=0) or 1
    diff_preview = np.round(diff / diff_peak * 255).clip(0, 255).astype(np.uint8)

    for idx, (x, y, w, h) in enumerate(crops, 1):
        for label, arr in (("ref", ref), ("candidate", cand), ("diff_scaled", diff_preview)):
            img = as_preview(arr[y : y + h, x : x + w])
            if scale != 1:
                img = img.resize((w * scale, h * scale), Image.Resampling.NEAREST)
            img.save(crop_dir / f"{idx:02d}_{label}.png")


def default_crops(width: int, height: int, size: int = 512) -> list[tuple[int, int, int, int]]:
    w = min(size, width)
    h = min(size, height)
    points = [
        (0, 0),
        ((width - w) // 2, (height - h) // 2),
        (max(0, width - w), max(0, height - h)),
    ]
    seen = set()
    crops = []
    for x, y in points:
        key = (x, y, w, h)
        if key not in seen:
            seen.add(key)
            crops.append(key)
    return crops


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [int(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,w,h")
    return tuple(parts)  # type: ignore[return-value]


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in value)


def file_size(path: Path | None) -> int | None:
    return path.stat().st_size if path and path.exists() else None


def maybe_butteraugli(exe: str | None, reference: Path, candidate: Path) -> float | None:
    if not exe:
        return None
    try:
        cp = run_cmd([exe, str(reference), str(candidate)], quiet=True)
    except Exception as exc:
        print(f"butteraugli skipped for {candidate.name}: {exc}", file=sys.stderr)
        return None
    tokens = cp.stdout.replace("\n", " ").split()
    for token in reversed(tokens):
        try:
            return float(token)
        except ValueError:
            pass
    print(f"could not parse butteraugli output for {candidate.name}: {cp.stdout}", file=sys.stderr)
    return None


def encode_decode(args: argparse.Namespace) -> list[Candidate]:
    out_dir = Path(args.out_dir)
    encoded = out_dir / "encoded"
    decoded = out_dir / "decoded"
    encoded.mkdir(parents=True, exist_ok=True)
    decoded.mkdir(parents=True, exist_ok=True)

    cjxl = find_exe("cjxl", args.cjxl)
    djxl = find_exe("djxl", args.djxl)
    magick = find_exe("magick", args.magick)
    if not cjxl or not djxl:
        raise SystemExit("encode-test needs cjxl and djxl on PATH, or pass --cjxl and --djxl.")

    ref = Path(args.reference)
    candidates: list[Candidate] = []

    lossless_jxl = encoded / "jxl_lossless.jxl"
    run_cmd([cjxl, str(ref), str(lossless_jxl), "-d", "0", "-e", str(args.effort)])
    lossless_decoded = decoded / "jxl_lossless.png"
    run_cmd([djxl, str(lossless_jxl), str(lossless_decoded)])
    candidates.append(Candidate("jxl_lossless", lossless_decoded, lossless_jxl))

    for distance in args.distance:
        label = f"jxl_d{str(distance).replace('.', '_')}"
        out_jxl = encoded / f"{label}.jxl"
        run_cmd([cjxl, str(ref), str(out_jxl), "-d", str(distance), "-e", str(args.effort)])
        out_png = decoded / f"{label}.png"
        run_cmd([djxl, str(out_jxl), str(out_png)])
        candidates.append(Candidate(label, out_png, out_jxl))

    if magick:
        tiff_zip = encoded / "tiff_zip.tif"
        run_cmd([magick, str(ref), "-compress", "Zip", str(tiff_zip)])
        candidates.append(Candidate("tiff_zip", tiff_zip, tiff_zip))

        jpg = encoded / f"jpeg_q{args.jpeg_quality}.jpg"
        run_cmd([magick, str(ref), "-quality", str(args.jpeg_quality), str(jpg)])
        jpg_png = decoded / f"jpeg_q{args.jpeg_quality}.png"
        run_cmd([magick, str(jpg), str(jpg_png)])
        candidates.append(Candidate(f"jpeg_q{args.jpeg_quality}", jpg_png, jpg))
    else:
        print("ImageMagick not found: skipping TIFF ZIP and JPEG sanity-check encodes.", file=sys.stderr)

    return candidates


def render_dng_files(paths: list[Path], args: argparse.Namespace) -> list[Path]:
    out_dir = Path(args.out_dir) / "rendered"
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for path in paths:
        if not path.exists():
            raise SystemExit(f"DNG does not exist: {path}")
        output = out_dir / f"{path.stem}.tif"
        command = args.render_command.format(input=str(path), output=str(output))
        run_cmd(shlex.split(command, posix=(os.name != "nt")))
        rendered.append(output)
    return rendered


def write_reports(out_dir: Path, rows: list[dict[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "metrics.csv"
    json_path = out_dir / "metrics.json"
    fields = [
        "name",
        "candidate",
        "encoded",
        "candidate_bytes",
        "encoded_bytes",
        "exact",
        "mae",
        "rmse",
        "psnr_db",
        "max_error",
        "ssim",
        "dssim",
        "butteraugli",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def compare(reference: Path, candidates: Iterable[Candidate], args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    ref, peak = load_image(reference)
    height, width = ref.shape[:2]
    crops = args.crop or default_crops(width, height, args.crop_size)
    butteraugli = find_exe("butteraugli", args.butteraugli)
    rows: list[dict[str, object]] = []

    for candidate in candidates:
        cand_raw, _ = load_image(candidate.path)
        cand = align_to_reference(ref, cand_raw)
        metrics = compute_metrics(ref, cand, peak)
        ba = maybe_butteraugli(butteraugli, reference, candidate.path)
        save_crops(ref, cand, out_dir, candidate.name, crops, args.crop_scale)
        row: dict[str, object] = {
            "name": candidate.name,
            "candidate": str(candidate.path),
            "encoded": str(candidate.encoded_path) if candidate.encoded_path else "",
            "candidate_bytes": file_size(candidate.path),
            "encoded_bytes": file_size(candidate.encoded_path),
            "butteraugli": ba,
        }
        row.update(metrics)
        rows.append(row)
        psnr = "inf" if math.isinf(float(metrics["psnr_db"])) else f"{metrics['psnr_db']:.3f}"
        print(f"{candidate.name}: exact={metrics['exact']} max={metrics['max_error']} mae={metrics['mae']:.6f} psnr={psnr} ssim={metrics['ssim']:.9f}")

    write_reports(out_dir, rows)
    print(f"\nWrote {out_dir / 'metrics.csv'}")
    print(f"Wrote crops under {out_dir / 'crops'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare rendered DNG/TIFF states and JPEG XL encodes.")
    sub = parser.add_subparsers(dest="command", required=True)

    enc_p = sub.add_parser("encode-test", help="encode/decode JXL variants from one rendered reference, then compare")
    add_common(enc_p)
    enc_p.add_argument("--distance", action="append", default=["0.5", "1.0"], help="JPEG XL distance for high-quality lossy tests; repeatable.")
    enc_p.add_argument("--effort", default="7", help="cjxl effort, usually 1-9.")
    enc_p.add_argument("--jpeg-quality", default="95", help="ImageMagick JPEG quality for sanity check.")
    enc_p.add_argument("--cjxl", help="path to cjxl executable.")
    enc_p.add_argument("--djxl", help="path to djxl executable.")
    enc_p.add_argument("--magick", help="path to ImageMagick magick executable.")

    cmp_p = sub.add_parser("compare-rendered", help="compare already-rendered candidate images")
    add_common(cmp_p)
    cmp_p.add_argument("candidates", nargs="+", help="candidate TIFF/PNG/JPEG files decoded/rendered to the same image state.")
    cmp_p.add_argument("--name", action="append", help="optional display name for each candidate, same order as candidates.")

    render_p = sub.add_parser("render-dng", help="render DNG files to TIFF using the same external command template")
    render_p.add_argument("dngs", nargs="+", help="DNG files to render.")
    render_p.add_argument("--render-command", required=True, help='command template, e.g. darktable-cli "{input}" "{output}"')
    render_p.add_argument("--out-dir", default="results", help="output directory.")

    dng_p = sub.add_parser("compare-dng", help="render DNG files with one command template, then compare rendered outputs")
    add_common(dng_p)
    dng_p.add_argument("candidates", nargs="+", help="candidate DNG files.")
    dng_p.add_argument("--render-command", required=True, help='command template, e.g. darktable-cli "{input}" "{output}"')
    dng_p.add_argument("--name", action="append", help="optional display name for each candidate, same order as candidates.")

    return parser


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("reference", help="reference rendered image, or reference DNG for compare-dng.")
    parser.add_argument("--out-dir", default="results", help="output directory for reports, crops, encodes, and decodes.")
    parser.add_argument("--crop", action="append", type=parse_crop, help="crop as x,y,w,h; repeatable. Defaults to corner/center/end crops.")
    parser.add_argument("--crop-size", type=int, default=512, help="default crop size when --crop is not provided.")
    parser.add_argument("--crop-scale", type=int, default=2, help="nearest-neighbor visual crop scale.")
    parser.add_argument("--butteraugli", help="path to butteraugli executable.")


def candidate_names(args: argparse.Namespace, paths: list[Path]) -> list[str]:
    names = args.name or []
    if names and len(names) != len(paths):
        raise SystemExit("--name must be supplied once per candidate when used")
    return names or [path.stem for path in paths]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "encode-test":
        reference = Path(args.reference)
        if not reference.exists():
            parser.error(f"reference does not exist: {reference}")
        candidates = encode_decode(args)
        compare(reference, candidates, args)
        return 0

    if args.command == "compare-rendered":
        reference = Path(args.reference)
        if not reference.exists():
            parser.error(f"reference does not exist: {reference}")
        candidate_paths = [Path(path) for path in args.candidates]
        missing = [str(path) for path in candidate_paths if not path.exists()]
        if missing:
            parser.error("candidate does not exist: " + ", ".join(missing))
        names = candidate_names(args, candidate_paths)
        compare(reference, [Candidate(names[i], path) for i, path in enumerate(candidate_paths)], args)
        return 0

    if args.command == "render-dng":
        rendered = render_dng_files([Path(path) for path in args.dngs], args)
        print("\nRendered files:")
        for path in rendered:
            print(path)
        return 0

    if args.command == "compare-dng":
        dng_paths = [Path(args.reference), *[Path(path) for path in args.candidates]]
        rendered = render_dng_files(dng_paths, args)
        reference = rendered[0]
        candidate_paths = rendered[1:]
        names = candidate_names(args, [Path(path) for path in args.candidates])
        compare(reference, [Candidate(names[i], path) for i, path in enumerate(candidate_paths)], args)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
