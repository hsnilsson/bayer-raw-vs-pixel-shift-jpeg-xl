from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from break_even_image_tools import (  # noqa: E402
    RegistrationResult,
    optional_tifffile,
    phase_correlation_shift,
    read_rgb_image,
    resize_rgb,
    resize_to_max_dim,
    shift_rgb,
    structure_metrics,
    unit_luma,
)
from PIL import Image  # noqa: E402


DEFAULT_CROP_PLAN = ROOT / "results/break_even_crop_guides/crop_plan.json"


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def require_16_bit_rgb(path: Path) -> None:
    tifffile = optional_tifffile()
    if tifffile is None:
        raise SystemExit(
            "16-bit TIFF support is required. Set JXL_PYDEPS to the project's TIFF dependency bundle."
        )
    image = tifffile.imread(path)
    if image.ndim != 3 or image.shape[2] < 3 or str(image.dtype) != "uint16":
        raise SystemExit(f"Expected 16-bit RGB TIFF: {relpath(path)}; got {image.shape} {image.dtype}")


def load_crop_specs(plan_path: Path, scan_set: str, set_id: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    if not plan_path.is_file():
        return []
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    case = payload.get("cases", {}).get(f"{scan_set}|{set_id}", {})
    crops: list[tuple[str, tuple[int, int, int, int]]] = []
    for index, item in enumerate(case.get("crops", []), 1):
        values = item.get("crop", [])
        if len(values) != 4:
            continue
        x, y, width, height = (int(value) for value in values)
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            continue
        crops.append((str(item.get("name") or f"manual-{index:02d}"), (x, y, width, height)))
    return crops


def rgb_diagnostics(reference: Any, candidate: Any) -> dict[str, Any]:
    ref = reference.astype("float64")
    cand = candidate.astype("float64")
    diff = cand - ref
    luma = diff[:, :, 0] * 0.2126 + diff[:, :, 1] * 0.7152 + diff[:, :, 2] * 0.0722
    return {
        "mean_bias_rgb_16bit": [float(value) for value in diff.mean(axis=(0, 1))],
        "rmse_rgb_16bit": float((diff * diff).mean() ** 0.5),
        "rmse_luma_16bit": float((luma * luma).mean() ** 0.5),
    }


def crop_image(image: Any, crop: tuple[int, int, int, int]) -> Any:
    x, y, width, height = crop
    return image[y : y + height, x : x + width]


def estimate_registration(reference: Any, candidate: Any, max_preview_dim: int) -> tuple[RegistrationResult, Any, Any]:
    reference_preview, _ = resize_to_max_dim(reference, max_preview_dim)
    height, width = reference_preview.shape[:2]
    candidate_preview = resize_rgb(candidate, (width, height), resample=Image.Resampling.BOX)
    shift_x_preview, shift_y_preview, peak, confidence = phase_correlation_shift(
        unit_luma(reference_preview), unit_luma(candidate_preview)
    )
    scale_x = reference.shape[1] / candidate.shape[1]
    scale_y = reference.shape[0] / candidate.shape[0]
    registration = RegistrationResult(
        scale_x=float(scale_x),
        scale_y=float(scale_y),
        shift_x_px=float(shift_x_preview * (reference.shape[1] / width)),
        shift_y_px=float(shift_y_preview * (reference.shape[0] / height)),
        overlap_fraction=1.0,
        phase_peak=float(peak),
        phase_peak_to_median=float(confidence),
        reference_shape=tuple(int(value) for value in reference.shape),
        candidate_shape=tuple(int(value) for value in candidate.shape),
    )
    registered_preview = shift_rgb(candidate_preview, shift_x_preview, shift_y_preview)
    return registration, reference_preview, registered_preview


def registered_candidate_crop(candidate: Any, registration: RegistrationResult, crop: tuple[int, int, int, int]) -> Any:
    x, y, width, height = crop
    inverse_scale_x = 1.0 / registration.scale_x
    inverse_scale_y = 1.0 / registration.scale_y
    channels = []
    for index in range(3):
        image = Image.fromarray(candidate[:, :, index].astype(np.float32), mode="F")
        transformed = image.transform(
            (width, height),
            Image.Transform.AFFINE,
            (
                inverse_scale_x,
                0.0,
                (x - registration.shift_x_px) * inverse_scale_x,
                0.0,
                inverse_scale_y,
                (y - registration.shift_y_px) * inverse_scale_y,
            ),
            resample=Image.Resampling.BICUBIC,
            fillcolor=0.0,
        )
        values = np.asarray(transformed, dtype=np.float32)
        channels.append(np.clip(np.rint(values), 0, 65535).astype(candidate.dtype))
    return np.ascontiguousarray(np.stack(channels, axis=2))


def evaluate_scope(name: str, reference: Any, candidate: Any, crop: tuple[int, int, int, int] | None) -> dict[str, Any]:
    ref = crop_image(reference, crop) if crop else reference
    cand = crop_image(candidate, crop) if crop else candidate
    if ref.shape != cand.shape:
        raise ValueError(f"{name}: incompatible shapes after registration: {ref.shape} != {cand.shape}")
    return {
        "scope": name,
        "crop": list(crop) if crop else None,
        "shape": [int(value) for value in ref.shape],
        "structure": asdict(structure_metrics(ref, cand, radius=2)),
        "rgb_diagnostic": rgb_diagnostics(ref, cand),
    }


def locally_register_crop(reference: Any, candidate: Any) -> tuple[Any, dict[str, float]]:
    shift_x, shift_y, peak, confidence = phase_correlation_shift(unit_luma(reference), unit_luma(candidate))
    phase_x = int(round(shift_x))
    phase_y = int(round(shift_y))
    choices = {(0, 0)}
    for dx in range(phase_x - 2, phase_x + 3):
        for dy in range(phase_y - 2, phase_y + 3):
            choices.add((dx, dy))

    best_candidate = candidate
    best_shift = (0.0, 0.0)
    best_score = structure_metrics(reference, candidate, radius=2).detail_correlation
    for dx, dy in sorted(choices):
        if (dx, dy) == (0, 0):
            continue
        trial = shift_rgb(candidate, dx, dy)
        score = structure_metrics(reference, trial, radius=2).detail_correlation
        if score > best_score:
            best_candidate = trial
            best_shift = (float(dx), float(dy))
            best_score = score

    # Grain and resolved film detail decorrelate sharply from subpixel offsets.
    # After the inexpensive integer search, refine around the best position at
    # quarter-pixel resolution so a small registration error is not reported as
    # a merge difference.
    refine_offsets = (-0.5, -0.25, 0.0, 0.25, 0.5)
    refine_choices = {
        (best_shift[0] + offset_x, best_shift[1] + offset_y)
        for offset_x in refine_offsets
        for offset_y in refine_offsets
    }
    for dx, dy in sorted(refine_choices):
        if dx == 0.0 and dy == 0.0:
            continue
        trial = shift_rgb(candidate, dx, dy)
        score = structure_metrics(reference, trial, radius=2).detail_correlation
        if score > best_score:
            best_candidate = trial
            best_shift = (float(dx), float(dy))
            best_score = score
    return (
        best_candidate,
        {
            "phase_shift_x_px": float(shift_x),
            "phase_shift_y_px": float(shift_y),
            "applied_shift_x_px": best_shift[0],
            "applied_shift_y_px": best_shift[1],
            "phase_peak": float(peak),
            "phase_peak_to_median": float(confidence),
            "selected_detail_correlation": float(best_score),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare an Imaging Edge Pixel Shift ARQ render with the matching PixelShift2DNG "
            "render. This is a merge control, not a JXL break-even verdict."
        )
    )
    parser.add_argument("--reference", type=Path, required=True, help="PixelShift2DNG PS16 neutral TIFF")
    parser.add_argument("--candidate", type=Path, required=True, help="Imaging Edge PS16 neutral TIFF")
    parser.add_argument("--output", type=Path, required=True, help="Local JSON result path")
    parser.add_argument("--scan-set", required=True)
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--crop-plan", type=Path, default=DEFAULT_CROP_PLAN)
    parser.add_argument("--max-preview-dim", type=int, default=2048)
    args = parser.parse_args()

    if args.max_preview_dim <= 0:
        raise SystemExit("--max-preview-dim must be positive")
    for path in (args.reference, args.candidate):
        if not path.is_file():
            raise SystemExit(f"Missing input: {relpath(path)}")
        require_16_bit_rgb(path)

    reference = read_rgb_image(args.reference)
    candidate = read_rgb_image(args.candidate)
    registration, preview_reference, preview_candidate = estimate_registration(
        reference, candidate, args.max_preview_dim
    )
    scopes = [evaluate_scope("full_preview", preview_reference, preview_candidate, None)]
    for name, crop in load_crop_specs(args.crop_plan, args.scan_set, args.set_id):
        x, y, width, height = crop
        if x + width <= reference.shape[1] and y + height <= reference.shape[0]:
            crop_reference = crop_image(reference, crop)
            crop_candidate = registered_candidate_crop(candidate, registration, crop)
            crop_candidate, local_registration = locally_register_crop(crop_reference, crop_candidate)
            scope = evaluate_scope(name, crop_reference, crop_candidate, None)
            scope["crop"] = list(crop)
            scope["local_registration"] = local_registration
            scopes.append(scope)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "comparison_kind": "merge_control",
        "interpretation": {
            "purpose": "Checks whether Sony Imaging Edge and PixelShift2DNG retain comparable PS16 detail from the same ARW sequence.",
            "not_a_jxl_verdict": True,
            "color_note": "RGB diagnostics expose render differences but are not color-accuracy or DeltaE claims because the two raw paths can carry different camera-profile interpretation.",
        },
        "scan_set": args.scan_set,
        "set_id": args.set_id,
        "reference": relpath(args.reference),
        "candidate": relpath(args.candidate),
        "reference_shape": [int(value) for value in reference.shape],
        "candidate_shape": [int(value) for value in candidate.shape],
        "registered_dtype": str(reference.dtype),
        "registration": asdict(registration),
        "scopes": scopes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote merge-control results to {relpath(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
