from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from run_public_latitude_stress import build_transforms, read_png  # noqa: E402


def read_token(data: bytes, pos: int) -> tuple[bytes, int]:
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1
    if pos < len(data) and data[pos] == ord("#"):
        while pos < len(data) and data[pos] not in b"\r\n":
            pos += 1
        return read_token(data, pos)
    start = pos
    while pos < len(data) and data[pos] not in b" \t\r\n":
        pos += 1
    return data[start:pos], pos


def read_ppm(path: Path) -> np.ndarray:
    data = path.read_bytes()
    magic, pos = read_token(data, 0)
    if magic != b"P6":
        raise ValueError(f"unsupported PPM magic in {path}: {magic!r}")
    width_token, pos = read_token(data, pos)
    height_token, pos = read_token(data, pos)
    max_token, pos = read_token(data, pos)
    width = int(width_token)
    height = int(height_token)
    max_value = int(max_token)
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1

    if max_value <= 255:
        dtype = np.uint8
        expected = width * height * 3
        arr = np.frombuffer(data[pos : pos + expected], dtype=dtype)
    elif max_value <= 65535:
        dtype = ">u2"
        expected = width * height * 3 * 2
        arr = np.frombuffer(data[pos : pos + expected], dtype=dtype).astype(np.uint16)
    else:
        raise ValueError(f"unsupported PPM max value {max_value}")
    return np.ascontiguousarray(arr.reshape((height, width, 3)))


def load_metrics(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_uint8(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    return np.round(np.clip(values, 0.0, 1.0) * 255).astype(np.uint8)


def resize(arr: np.ndarray, size: int) -> Image.Image:
    image = Image.fromarray(arr)
    if image.width <= size and image.height <= size:
        return image
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    return image


def abs_diff_panel(ref: np.ndarray, cand: np.ndarray, gain: float) -> np.ndarray:
    diff = np.abs(cand - ref) * gain
    return to_uint8(np.repeat(np.clip(diff.mean(axis=2, keepdims=True), 0.0, 1.0), 3, axis=2))


def signed_diff_panel(ref: np.ndarray, cand: np.ndarray, gain: float) -> np.ndarray:
    diff = np.clip((cand - ref) * gain, -1.0, 1.0)
    panel = np.zeros_like(diff)
    positive = np.clip(diff, 0.0, 1.0)
    negative = np.clip(-diff, 0.0, 1.0)
    panel[:, :, 1] = positive.mean(axis=2)
    panel[:, :, 0] = negative.mean(axis=2)
    panel[:, :, 2] = negative.mean(axis=2)
    return to_uint8(panel)


def draw_label(image: Image.Image, text: str) -> Image.Image:
    labelled = Image.new("RGB", (image.width, image.height + 28), "white")
    labelled.paste(image, (0, 28))
    draw = ImageDraw.Draw(labelled)
    draw.rectangle((0, 0, image.width, 28), fill=(248, 248, 248))
    draw.text((8, 7), text, fill=(20, 20, 20))
    return labelled


def make_panel(
    reference: np.ndarray,
    candidate: np.ndarray,
    transform_name: str,
    distance: str,
    metrics: dict[str, str],
    output: Path,
    panel_size: int,
    diff_gain: float,
) -> None:
    transform = {item.name: item for item in build_transforms(reference)}[transform_name]
    ref_t = transform.apply(reference)
    cand_t = transform.apply(candidate)
    pieces = [
        draw_label(resize(to_uint8(ref_t), panel_size), "reference"),
        draw_label(resize(to_uint8(cand_t), panel_size), f"JXL d={distance}"),
        draw_label(resize(abs_diff_panel(ref_t, cand_t, diff_gain), panel_size), f"abs diff x{diff_gain:g}"),
        draw_label(resize(signed_diff_panel(ref_t, cand_t, diff_gain), panel_size), f"signed diff x{diff_gain:g}"),
    ]
    gutter = 10
    width = sum(piece.width for piece in pieces) + gutter * (len(pieces) - 1)
    height = max(piece.height for piece in pieces) + 48
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    title = (
        f"{metrics['image_id']} | {transform_name} | d={distance} | "
        f"MAE {float(metrics['mae_16bit']):.2f} | PSNR {float(metrics['psnr_db']):.2f} dB"
    )
    draw.text((8, 8), title, fill=(0, 0, 0))
    x = 0
    for piece in pieces:
        panel.paste(piece, (x, 48))
        x += piece.width + gutter
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.save(output)


def write_index(output_dir: Path, rows: list[dict[str, str]], panel_paths: list[Path]) -> None:
    lines = [
        "# Public Latitude Stress Panels",
        "",
        "Each panel shows reference, decoded JXL candidate, amplified absolute difference, and amplified signed difference.",
        "",
    ]
    for path, row in zip(panel_paths, rows):
        relative = path.relative_to(output_dir)
        lines.append(
            f"## {row['image_id']} | d={row['distance']} | {row['transform']}"
        )
        lines.append("")
        lines.append(
            f"MAE `{float(row['mae_16bit']):.2f}`, PSNR `{float(row['psnr_db']):.2f} dB`, "
            f"p99 pixel max error `{float(row['p99_pixel_max_error_16bit']):.1f}`."
        )
        lines.append("")
        lines.append(f"![panel]({relative.as_posix()})")
        lines.append("")
    (output_dir / "PANELS.md").write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create visual panels for public latitude stress results.")
    parser.add_argument("results_dir", type=Path, help="directory containing metrics.csv and per-image outputs")
    parser.add_argument("--panel-size", type=int, default=512)
    parser.add_argument("--diff-gain", type=float, default=64.0)
    parser.add_argument(
        "--transforms",
        nargs="*",
        default=["identity", "negative_density_print", "negative_density_hard_print"],
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    results_dir = args.results_dir
    rows = [
        row for row in load_metrics(results_dir / "metrics.csv")
        if row["transform"] in set(args.transforms)
    ]
    panel_paths: list[Path] = []
    written_rows: list[dict[str, str]] = []
    references: dict[str, np.ndarray] = {}
    candidates: dict[tuple[str, str], np.ndarray] = {}

    for row in rows:
        image_id = row["image_id"]
        distance = row["distance"]
        image_dir = results_dir / image_id
        if image_id not in references:
            references[image_id] = read_ppm(image_dir / "reference.ppm")
        key = (image_id, distance)
        if key not in candidates:
            candidates[key] = read_png(image_dir / f"jxl_d{distance.replace('.', '_')}.png")
        output = results_dir / "panels" / image_id / f"d{distance.replace('.', '_')}_{row['transform']}.png"
        make_panel(
            references[image_id],
            candidates[key],
            row["transform"],
            distance,
            row,
            output,
            args.panel_size,
            args.diff_gain,
        )
        panel_paths.append(output)
        written_rows.append(row)
        print(f"Wrote {output}")

    write_index(results_dir, written_rows, panel_paths)
    print(f"Wrote {results_dir / 'PANELS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
