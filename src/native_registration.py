"""Audited subpixel refinement of selected native RAW61 baselines.

The frozen core engine supplies the coarse translation. A band-limited phase
fit on its common interior avoids giving aliased test-target frequencies equal
weight. Only the source RAW is resampled; PS16 and JXL codes are never shifted.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from incremental_cache import sha256_file

METHOD = "band-limited-phase-dft-raw-source-v1"
CUTOFF = .15  # cycles per PS16 pixel, below the upscaled RAW Nyquist frequency
POWER_FLOOR = 1e-4  # do not amplify near-empty/noise-dominated frequency bins
STEP = .025
RADIUS = 2
BORDER = 32
MAX_RESIDUAL = .10
PLAN = "metadata/native_registration_plan.json"
CODE = ("src/native_registration.py", "scripts/refine_native_registration.py", PLAN)


def provenance(root: Path) -> dict:
    return {"method": METHOD, "code": {p: sha256_file(root / p) for p in CODE},
            "cutoff_cycles_per_pixel": CUTOFF, "grid_step_px": STEP,
            "relative_cross_power_floor": POWER_FLOOR,
            "search_radius_px": RADIUS, "interior_border_px": BORDER,
            "max_residual_px": MAX_RESIDUAL,
            "resampling": "Single bicubic sample from original linear RAW; no candidate fitting"}


def selected(root: Path, frame: dict) -> list[str]:
    plan = json.loads((root / PLAN).read_text(encoding="utf-8"))
    return next((c["crops"] for c in plan["cases"]
                 if (c["slug"], c["set_id"]) == (frame["slug"], frame["set_id"])), [])


def validate_recipe(root: Path, frame: dict, recipe: dict) -> None:
    names = selected(root, frame)
    if recipe.get("native_registration") != (provenance(root) if names else None):
        raise ValueError("Missing or changed native registration recipe")
    for scope in recipe["scopes"]:
        a = scope["alignment"]
        if scope["name"] in names:
            if a.get("method") != METHOD or not a["applied"]:
                raise ValueError("Missing approved subpixel registration")
            residual = a.get("residual_xy_px", [])
            if len(residual) != 2 or not all(math.isfinite(v) and abs(v) <= MAX_RESIDUAL for v in residual):
                raise ValueError("Native registration residual exceeds tolerance")
        elif a.get("method") == METHOD:
            raise ValueError("Undeclared native registration refinement")


def residual_shift(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    """Evaluate a local inverse DFT at 1/40-pixel spacing (x, y to apply)."""
    import numpy as np
    if reference.shape != candidate.shape or reference.ndim != 2 or min(reference.shape) < 64:
        raise ValueError("Registration needs matching 2D interiors at least 64 pixels wide")
    h, w = reference.shape
    a, b = [np.asarray(x, dtype=np.float64) for x in (reference, candidate)]
    a, b = a - a.mean(), b - b.mean()
    if not np.isfinite(a).all() or not np.isfinite(b).all() or min(a.std(), b.std()) < 1e-7:
        raise ValueError("Insufficient finite registration signal")
    window = np.hanning(h)[:, None] * np.hanning(w)[None, :]
    power = np.fft.fft2(a * window) * np.conj(np.fft.fft2(b * window))
    fy, fx = np.fft.fftfreq(h), np.fft.fftfreq(w)
    weight = np.exp(-(np.hypot(fy[:, None], fx[None, :]) / CUTOFF) ** 4)
    spectrum = power / np.maximum(abs(power), max(float(abs(power).max()) * POWER_FLOOR, 1e-12)) * weight
    grid = np.arange(-round(RADIUS / STEP), round(RADIUS / STEP) + 1) * STEP
    corr = (np.exp(2j*np.pi*np.outer(grid, fy)) @ spectrum @ np.exp(2j*np.pi*np.outer(fx, grid))).real
    iy, ix = np.unravel_index(int(corr.argmax()), corr.shape)
    if ix in (0, len(grid)-1) or iy in (0, len(grid)-1):
        raise ValueError("Subpixel refinement reached its search boundary")
    return round(float(grid[ix]), 3), round(float(grid[iy]), 3)


def valid_support(shape, dx, dy):
    left, top = math.ceil(max(dx, 0)) + 2, math.ceil(max(dy, 0)) + 2
    right, bottom = math.ceil(max(-dx, 0)) + 2, math.ceil(max(-dy, 0)) + 2
    return [left, top, shape[1] - left - right, shape[0] - top - bottom]


def registered_raw(raw, profile, crop, shape, global_shift, alignment):
    """Reconstruct exactly the RAW array used by measurements and the viewer."""
    import numpy as np
    from report_transforms import sample_raw_crop
    if alignment.get("method") == METHOD:
        shift = tuple(g + alignment[k] for g, k in zip(global_shift, ("shift_x_px", "shift_y_px")))
        return sample_raw_crop(raw, profile, crop, shape, shift)
    linear = sample_raw_crop(raw, profile, crop, shape, global_shift)
    ix, iy = (int(alignment["shift_x_px"]), int(alignment["shift_y_px"])) if alignment["applied"] else (0, 0)
    return np.roll(linear, (iy, ix), (0, 1))


def refine(reference, coarse_raw, source_raw, profile, crop, shape, global_shift, coarse):
    if not coarse["applied"] or max(abs(coarse[k]) for k in ("shift_x_px", "shift_y_px")) >= BORDER:
        raise ValueError("A confident coarse registration inside the interior margin is required")
    interior = (slice(BORDER, -BORDER), slice(BORDER, -BORDER))
    a = (reference @ profile.matrix[1])[interior]
    b = (coarse_raw @ profile.matrix[1])[interior]
    rx, ry = residual_shift(a, b)
    dx, dy = round(coarse["shift_x_px"] + rx, 3), round(coarse["shift_y_px"] + ry, 3)
    alignment = dict(coarse, method=METHOD, shift_x_px=dx, shift_y_px=dy,
                     integer_shift_xy_px=[coarse["shift_x_px"], coarse["shift_y_px"]],
                     refinement_xy_px=[rx, ry], valid_xywh=valid_support(reference.shape, dx, dy))
    aligned = registered_raw(source_raw, profile, crop, shape, global_shift, alignment)
    residual = residual_shift(a, (aligned @ profile.matrix[1])[interior])
    if max(map(abs, residual)) > MAX_RESIDUAL:
        raise ValueError("Subpixel registration did not converge within tolerance")
    alignment["residual_xy_px"] = list(residual)
    v = alignment["valid_xywh"]
    alignment["valid_fraction"] = v[2] * v[3] / (reference.shape[0] * reference.shape[1])
    return aligned, alignment
