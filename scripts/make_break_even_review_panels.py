from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from break_even_image_tools import (  # noqa: E402
    crop,
    phase_correlation_shift,
    read_rgb_image,
    resize_rgb,
    resize_to_max_dim,
    shift_rgb,
    unit_luma,
)
import run_local_scan_study as local_study  # noqa: E402
from run_public_latitude_stress import build_transforms  # noqa: E402


DEFAULT_MATRIX = ROOT / "results/archival_break_even/archival_break_even_matrix.csv"
DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_REGISTERED_ROOT = ROOT / "outputs/registered_raw61_to_ps16"
DEFAULT_RENDERED_JXL_ROOT = ROOT / "outputs/rendered_ps16_jxl_matrix"
DEFAULT_OUTPUT_DIR = ROOT / "results/break_even_review_panels"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"
DEFAULT_LEVELS = ["d020", "d022", "d025", "d028", "d030"]
DEFAULT_TRANSFORMS = ["identity", "negative_density_hard_print"]


@dataclass(frozen=True)
class ReviewCase:
    scan_set: str
    set_id: str
    reason: str


@dataclass(frozen=True)
class LocalAlignment:
    shift_x_px: float
    shift_y_px: float
    confidence: float
    applied: bool


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_crop_plan(path: Path | None) -> dict[tuple[str, str], list[tuple[str, str]]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for item in payload.get("cases", {}).values():
        key = (str(item.get("scan_set", "")), str(item.get("set_id", "")))
        specs = []
        for crop_item in item.get("crops", []):
            values = crop_item.get("crop", [])
            if len(values) == 4:
                specs.append((str(crop_item.get("name", f"manual-{len(specs) + 1:02d}")), ",".join(str(value) for value in values)))
        if specs:
            plan[key] = specs
    return plan


def as_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or "")
    except ValueError:
        return default


def find_tool(name: str, fallback: Path, explicit: Path | None = None) -> str:
    candidates = [str(explicit)] if explicit else []
    candidates.extend([name, str(fallback)])
    for candidate in candidates:
        found = shutil.which(candidate) if "\\" not in candidate and "/" not in candidate else None
        if found:
            return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    raise SystemExit(f"Could not find {name}; pass --{name} or place it at {fallback}")


def parse_case(value: str) -> ReviewCase:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError('case must be "scan set|set id"')
    return ReviewCase(parts[0], parts[1], "manual")


def choose_cases(rows: list[dict[str, str]], limit: int) -> list[ReviewCase]:
    chosen: list[ReviewCase] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, str], reason: str) -> None:
        key = (row.get("scan_set", ""), row.get("set_id", ""))
        if not all(key) or key in seen:
            return
        seen.add(key)
        chosen.append(ReviewCase(key[0], key[1], reason))

    artifact_rows = sorted(
        rows,
        key=lambda row: (row.get("artifact_risk") != "high", row.get("scan_set", ""), row.get("set_id", "")),
    )
    for row in artifact_rows:
        if row.get("artifact_risk") == "high":
            add(row, "artifact-risk")
            break

    complete = [row for row in rows if row.get("evidence_status") == "complete"]
    for row in sorted(complete, key=lambda item: as_float(item.get("raw61_color_delta_e00_p95_stress")), reverse=True):
        add(row, "largest-raw61-color-baseline")
        if len(chosen) >= limit:
            return chosen
    for row in sorted(complete, key=lambda item: as_float(item.get("jxl_structure_loss")), reverse=True):
        add(row, "largest-jxl-structure-loss")
        if len(chosen) >= limit:
            return chosen
    return chosen[:limit]


def ps16_path(renders_root: Path, scan_set: str, set_id: str) -> Path:
    return renders_root / local_study.slugify(scan_set) / set_id / "ps16.tif"


def raw61_path(registered_root: Path, scan_set: str, set_id: str) -> Path:
    return registered_root / local_study.slugify(scan_set) / set_id / "raw61_registered_to_ps16.tif"


def jxl_path(rendered_jxl_root: Path, scan_set: str, set_id: str, level: str) -> Path:
    return rendered_jxl_root / local_study.slugify(scan_set) / set_id / level / "ps16.jxl"


def run_decode(djxl: str, source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [djxl, str(source), str(output)],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def high_detail_crop(reference: np.ndarray, crop_size: int, margin: int) -> tuple[int, int, int, int]:
    height, width = reference.shape[:2]
    size = min(crop_size, height, width)
    preview, scale = resize_to_max_dim(reference, 1024)
    luma = unit_luma(preview)
    gy, gx = np.gradient(luma)
    detail = gx * gx + gy * gy
    win = max(8, round(size * scale))
    py_margin = max(0, round(margin * scale))
    px_margin = py_margin
    valid = detail.copy()
    if py_margin and px_margin and valid.shape[0] > py_margin * 2 and valid.shape[1] > px_margin * 2:
        valid[:py_margin, :] = 0
        valid[-py_margin:, :] = 0
        valid[:, :px_margin] = 0
        valid[:, -px_margin:] = 0
    pad = win // 2
    padded = np.pad(valid, pad, mode="constant")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    sums = integral[win:, win:] - integral[:-win, win:] - integral[win:, :-win] + integral[:-win, :-win]
    y, x = np.unravel_index(int(np.argmax(sums)), sums.shape)
    center_x = (x + win / 2 - pad) / max(scale, 1e-12)
    center_y = (y + win / 2 - pad) / max(scale, 1e-12)
    crop_x = int(round(center_x - size / 2))
    crop_y = int(round(center_y - size / 2))
    crop_x = min(max(crop_x, 0), max(0, width - size))
    crop_y = min(max(crop_y, 0), max(0, height - size))
    return crop_x, crop_y, size, size


def default_crops(reference: np.ndarray, crop_size: int) -> list[tuple[str, str]]:
    height, width = reference.shape[:2]
    size = min(crop_size, height, width)
    center = ((width - size) // 2, (height - size) // 2, size, size)
    detail = high_detail_crop(reference, crop_size=size, margin=size // 2)
    crops = [("center", ",".join(str(v) for v in center))]
    if detail != center:
        crops.append(("auto-detail", ",".join(str(v) for v in detail)))
    return crops


def to_display(arr: np.ndarray) -> Image.Image:
    values = np.asarray(arr, dtype=np.float32)
    if values.ndim == 2:
        values = np.repeat(values[:, :, None], 3, axis=2)
    if np.issubdtype(arr.dtype, np.integer):
        values = values / float(np.iinfo(arr.dtype).max)
    low, high = np.percentile(values, [0.5, 99.5])
    if high <= low:
        high = low + 1e-6
    values = np.clip((values - low) / (high - low), 0.0, 1.0)
    return Image.fromarray(np.round(values[:, :, :3] * 255).astype(np.uint8), mode="RGB")


def diff_display(reference: np.ndarray, candidate: np.ndarray, gain: float) -> Image.Image:
    ref = reference.astype(np.float32)
    cand = candidate.astype(np.float32)
    if np.issubdtype(reference.dtype, np.integer):
        ref = ref / float(np.iinfo(reference.dtype).max)
    if np.issubdtype(candidate.dtype, np.integer):
        cand = cand / float(np.iinfo(candidate.dtype).max)
    diff = np.clip(np.abs(cand[:, :, :3] - ref[:, :, :3]) * gain, 0.0, 1.0)
    return Image.fromarray(np.round(diff * 255).astype(np.uint8), mode="RGB")


def checkerboard(reference: np.ndarray, candidate: np.ndarray, square: int = 48) -> Image.Image:
    ref = np.asarray(to_display(reference))
    cand = np.asarray(to_display(candidate))
    yy, xx = np.mgrid[: ref.shape[0], : ref.shape[1]]
    mask = ((xx // square + yy // square) % 2).astype(bool)
    out = ref.copy()
    out[mask] = cand[mask]
    return Image.fromarray(out, mode="RGB")


def label(image: Image.Image, title: str, help_text: str) -> Image.Image:
    pad = 58
    out = Image.new("RGB", (image.width, image.height + pad), "white")
    out.paste(image, (0, pad))
    draw = ImageDraw.Draw(out)
    draw.text((6, 6), title, fill="black")
    draw.multiline_text((6, 23), help_text, fill=(70, 70, 70), spacing=2)
    return out


def local_align_raw61(reference: np.ndarray, raw61: np.ndarray, max_shift: float) -> tuple[np.ndarray, LocalAlignment]:
    shift_x, shift_y, _peak, confidence = phase_correlation_shift(unit_luma(reference), unit_luma(raw61))
    applied = confidence > 20.0 and abs(shift_x) <= max_shift and abs(shift_y) <= max_shift
    if not applied:
        return raw61, LocalAlignment(shift_x, shift_y, confidence, False)
    return shift_rgb(raw61, shift_x, shift_y), LocalAlignment(shift_x, shift_y, confidence, True)


def compose_panel(
    reference: np.ndarray,
    raw61: np.ndarray,
    jxl: np.ndarray,
    title: str,
    transform_name: str,
    output: Path,
    panel_size: int,
    diff_gain: float,
    local_alignment: LocalAlignment,
) -> None:
    transforms = {transform.name: transform for transform in build_transforms(reference)}
    transform = transforms[transform_name]
    ref_t = transform.apply(reference)
    raw_t = transform.apply(raw61)
    jxl_t = transform.apply(jxl)
    alignment_text = (
        f"local RAW61 shift x={local_alignment.shift_x_px:.2f}, "
        f"y={local_alignment.shift_y_px:.2f}, "
        f"confidence={local_alignment.confidence:.1f}, "
        f"applied={str(local_alignment.applied).lower()}"
    )
    pieces = [
        label(
            to_display(ref_t).resize((panel_size, panel_size), Image.Resampling.BOX),
            "PS16 reference",
            "The comparison target\nrendered from PixelShift 16",
        ),
        label(
            to_display(raw_t).resize((panel_size, panel_size), Image.Resampling.BOX),
            "RAW61 local aligned",
            "Single-shot RAW after\ncrop-local alignment",
        ),
        label(
            to_display(jxl_t).resize((panel_size, panel_size), Image.Resampling.BOX),
            "PS16 JXL",
            "Decoded JPEG XL made\nfrom the PS16 render",
        ),
        label(
            diff_display(ref_t, raw_t, diff_gain).resize((panel_size, panel_size), Image.Resampling.BOX),
            f"RAW61 diff x{diff_gain:g}",
            "Difference from PS16;\nbright means different",
        ),
        label(
            diff_display(ref_t, jxl_t, diff_gain).resize((panel_size, panel_size), Image.Resampling.BOX),
            f"JXL diff x{diff_gain:g}",
            "Codec error versus PS16;\nnear-black is good",
        ),
        label(
            checkerboard(ref_t, raw_t).resize((panel_size, panel_size), Image.Resampling.BOX),
            "PS16/RAW61 checker",
            "Alternates both images;\ncheck remaining alignment",
        ),
    ]
    gap = 8
    header = 52
    width = sum(piece.width for piece in pieces) + gap * (len(pieces) - 1)
    height = header + max(piece.height for piece in pieces)
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    draw.text((6, 9), title, fill="black")
    draw.text((6, 28), alignment_text, fill=(70, 70, 70))
    x = 0
    for piece in pieces:
        panel.paste(piece, (x, header))
        x += piece.width + gap
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.save(output)


def iter_levels(requested: Iterable[str], case_rows: list[dict[str, str]], scan_set: str, set_id: str) -> list[str]:
    available = {
        row.get("level", "")
        for row in case_rows
        if row.get("scan_set") == scan_set and row.get("set_id") == set_id
    }
    return [level for level in requested if level in available]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create local visual review panels for RAW61 versus standalone PS16 JXL break-even cases."
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--rendered-jxl-root", type=Path, default=DEFAULT_RENDERED_JXL_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--djxl", type=Path)
    parser.add_argument("--case", action="append", type=parse_case)
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--transform", action="append", default=None)
    parser.add_argument("--crop", action="append", default=None, help="Crop as x,y,width,height in PS16 coordinates.")
    parser.add_argument("--crop-plan", type=Path, help="JSON crop plan produced by read_crop_selection_guides.py.")
    parser.add_argument("--case-limit", type=int, default=3)
    parser.add_argument("--crop-size", type=int, default=768)
    parser.add_argument("--panel-size", type=int, default=360)
    parser.add_argument("--diff-gain", type=float, default=16.0)
    parser.add_argument("--disable-local-raw61-align", action="store_true")
    parser.add_argument("--max-local-shift", type=float, default=32.0)
    parser.add_argument("--force", action="store_true", help="rewrite existing panel PNGs")
    args = parser.parse_args()

    if args.crop_size <= 0 or args.panel_size <= 0:
        raise SystemExit("--crop-size and --panel-size must be positive")
    rows = read_csv_rows(args.matrix)
    crop_plan = read_crop_plan(args.crop_plan)
    cases = args.case or choose_cases(rows, args.case_limit)
    levels = args.level or DEFAULT_LEVELS
    transforms = args.transform or DEFAULT_TRANSFORMS
    djxl = find_tool("djxl", DEFAULT_DJXL, args.djxl)

    index_lines = [
        "# Break-even Review Panels",
        "",
        "Local/private panels for reviewing whether RAW61-vs-PS16 baseline differences are real or pipeline artifacts.",
        "",
        "Read each panel left to right:",
        "",
        "- `PS16 reference`: the rendered PixelShift 16 target for this test.",
        "- `RAW61 local aligned`: the single-shot RAW render after crop-local x/y alignment.",
        "- `PS16 JXL`: the decoded JPEG XL candidate made from the PS16 render.",
        "- `RAW61 diff x16`: absolute difference between RAW61 and PS16, amplified 16x.",
        "- `JXL diff x16`: absolute difference between JXL and PS16, amplified 16x.",
        "- `PS16/RAW61 checker`: alternating squares from PS16 and RAW61; visible jumps indicate remaining alignment or rendering mismatch.",
        "",
        "Diff panels are diagnostic. Bright pixels mean different from PS16; they do not by themselves prove which image is better.",
        "",
    ]
    written = 0
    reused = 0
    with tempfile.TemporaryDirectory(prefix="break-even-jxl-") as temp_dir:
        temp_root = Path(temp_dir)
        for case in cases:
            ref_path = ps16_path(args.renders_root, case.scan_set, case.set_id)
            raw_path = raw61_path(args.registered_root, case.scan_set, case.set_id)
            if not ref_path.is_file() or not raw_path.is_file():
                index_lines.append(f"- skipped `{case.scan_set}/{case.set_id}`: missing reference or RAW61 render")
                continue
            reference_full = read_rgb_image(ref_path)
            raw_full = read_rgb_image(raw_path)
            crop_specs = [(f"manual-{idx:02d}", value) for idx, value in enumerate(args.crop or [], 1)]
            if not crop_specs:
                crop_specs = crop_plan.get((case.scan_set, case.set_id), [])
            if not crop_specs:
                crop_specs = default_crops(reference_full, args.crop_size)
            case_dir = args.output_dir / local_study.slugify(case.scan_set) / case.set_id
            index_lines.append(f"## {case.scan_set} / {case.set_id}")
            index_lines.append("")
            index_lines.append(f"Reason: {case.reason}")
            index_lines.append("")
            for level in iter_levels(levels, rows, case.scan_set, case.set_id):
                source_jxl = jxl_path(args.rendered_jxl_root, case.scan_set, case.set_id, level)
                if not source_jxl.is_file():
                    index_lines.append(f"- skipped `{level}`: missing `{relpath(source_jxl)}`")
                    continue
                output_specs = [
                    (
                        crop_name,
                        crop_spec,
                        transform_name,
                        case_dir / f"{level}_{crop_name}_{transform_name}.png",
                        f"{case.scan_set} / {case.set_id} / {level} / {crop_name} / {transform_name}",
                    )
                    for crop_name, crop_spec in crop_specs
                    for transform_name in transforms
                ]
                if not args.force and output_specs and all(output.is_file() for *_unused, output, _title in output_specs):
                    for *_unused, output, _title in output_specs:
                        index_lines.append(f"- [{output.name}]({relpath(output, args.output_dir)})")
                    reused += len(output_specs)
                    continue
                decoded = temp_root / local_study.slugify(case.scan_set) / case.set_id / level / "ps16_candidate.ppm"
                run_decode(djxl, source_jxl, decoded)
                jxl_full = read_rgb_image(decoded)
                for crop_name, crop_spec, transform_name, output, title in output_specs:
                    if output.is_file() and not args.force:
                        index_lines.append(f"- [{output.name}]({relpath(output, args.output_dir)})")
                        reused += 1
                        continue
                    ref_crop = crop(reference_full, crop_spec)
                    raw_crop = crop(raw_full, crop_spec)
                    jxl_crop = crop(jxl_full, crop_spec)
                    if args.disable_local_raw61_align:
                        aligned_raw_crop = raw_crop
                        alignment = LocalAlignment(0.0, 0.0, 0.0, False)
                    else:
                        aligned_raw_crop, alignment = local_align_raw61(ref_crop, raw_crop, args.max_local_shift)
                    compose_panel(
                        ref_crop,
                        aligned_raw_crop,
                        jxl_crop,
                        title,
                        transform_name,
                        output,
                        panel_size=args.panel_size,
                        diff_gain=args.diff_gain,
                        local_alignment=alignment,
                    )
                    index_lines.append(f"- [{output.name}]({relpath(output, args.output_dir)})")
                    written += 1
            index_lines.append("")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"Wrote {written} panel(s) to {relpath(args.output_dir)}; reused {reused} existing panel(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
