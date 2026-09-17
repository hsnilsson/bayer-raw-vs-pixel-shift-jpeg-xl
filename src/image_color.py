"""Explicit encoded-RGB -> linear-light -> display contract for report images.

Matrix/TRC ICC profiles are evaluated at floating-point precision. Camera RGB
and LUT profiles must not silently fall back to a named display colour space.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

import numpy as np
from PIL import Image

D50 = np.array([0.9642, 1.0, 0.8249])
D65_TO_D50 = np.array([[1.0479298, .0229468, -.0501922],
                       [.0296278, .9904345, -.0170738],
                       [-.0092430, .0150552, .7518743]])
SRGB_TO_XYZ_D65 = np.array([[.4124564, .3575761, .1804375],
                           [.2126729, .7151522, .0721750],
                           [.0193339, .1191920, .9503041]])
XYZ_D50_TO_SRGB = np.linalg.inv(D65_TO_D50 @ SRGB_TO_XYZ_D65)


def unit_rgb(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"Expected HxWx3 RGB, got {arr.shape}")
    if arr.dtype.kind == "u" and arr.dtype.itemsize in (1, 2):
        return arr.astype(np.float32) / np.iinfo(arr.dtype).max
    if arr.dtype.kind == "f" and np.isfinite(arr).all():
        return arr.astype(np.float32, copy=False)
    raise ValueError(f"Unsupported or nonfinite pixel representation: {arr.dtype}")


def srgb_decode(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x)
    return np.where(x <= .04045, x / 12.92, np.maximum((x + .055) / 1.055, 0) ** 2.4)


def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x)
    return np.where(x <= .0031308, 12.92 * x, 1.055 * np.maximum(x, 0) ** (1 / 2.4) - .055)


def decode_curve(x: np.ndarray, curve: dict) -> np.ndarray:
    if curve["kind"] == "srgb":
        return srgb_decode(x)
    if curve["kind"] == "gamma":
        return np.maximum(x, 0) ** curve["gamma"]
    if curve["kind"] == "table":
        y = np.asarray(curve["values"])
        return np.interp(x, np.linspace(0, 1, len(y)), y)
    p = curve["parameters"]
    kind = curve["function"]
    g = p[0]
    if kind == 0:
        return np.maximum(x, 0) ** g
    a, b = p[1:3]
    threshold = -b / a if kind in (1, 2) else p[4]
    high = np.maximum(a * x + b, 0) ** g
    low = np.zeros_like(x)
    if kind == 2:
        high, low = high + p[3], low + p[3]
    elif kind == 3:
        low = p[3] * x
    elif kind == 4:
        high, low = high + p[5], p[3] * x + p[6]
    return np.where(x >= threshold, high, low)


@dataclass(frozen=True)
class RgbProfile:
    name: str
    sha256: str
    matrix: np.ndarray
    curves: tuple[dict, dict, dict]

    def linearize(self, values: np.ndarray) -> np.ndarray:
        rgb = unit_rgb(values)
        return np.stack([decode_curve(rgb[..., i], self.curves[i]) for i in range(3)], axis=-1).astype(np.float32)

    def display(self, linear: np.ndarray) -> np.ndarray:
        return srgb_encode(np.asarray(linear) @ (XYZ_D50_TO_SRGB @ self.matrix).T)

    def encode_u16(self, linear: np.ndarray) -> np.ndarray:
        """Inverse monotone TRC, used only for quantized browser payloads."""
        codes = np.linspace(0, 1, 65536)
        encoded = np.stack([np.interp(linear[..., i], decode_curve(codes, self.curves[i]), codes)
                            for i in range(3)], axis=-1)
        return np.rint(encoded * 65535).astype(np.uint16)

    def recipe(self) -> dict:
        return {"name": self.name, "icc_sha256": self.sha256,
                "rgb_to_xyz_d50": self.matrix.tolist(),
                "linear_to_srgb": (XYZ_D50_TO_SRGB @ self.matrix).tolist(),
                "curves": list(self.curves)}


SRGB = RgbProfile("sRGB", "", D65_TO_D50 @ SRGB_TO_XYZ_D65,
                  ({"kind": "srgb"},) * 3)


def profile_from_icc(data: bytes) -> RgbProfile:
    if len(data) < 132 or data[36:40] != b"acsp" or data[16:20] != b"RGB " or data[20:24] != b"XYZ ":
        raise ValueError("A valid RGB matrix/TRC ICC profile with XYZ PCS is required")
    declared = struct.unpack_from(">I", data)[0]
    if declared != len(data):
        raise ValueError("ICC length does not match its header")
    tags = {}
    for i in range(struct.unpack_from(">I", data, 128)[0]):
        key, offset, length = struct.unpack_from(">4sII", data, 132 + 12 * i)
        if offset + length > len(data):
            raise ValueError("ICC tag exceeds profile length")
        tags[key] = data[offset:offset + length]
    if any(k in tags for k in (b"A2B0", b"B2A0")):
        raise ValueError("LUT ICC profiles require an explicit colour-management conversion")
    def fixed(block: bytes, offset: int, count: int) -> list[float]:
        return [v / 65536 for v in struct.unpack_from(">" + "i" * count, block, offset)]
    def curve(block: bytes) -> dict:
        if block[:4] == b"para":
            kind = struct.unpack_from(">H", block, 8)[0]
            counts = [1, 3, 4, 5, 7]
            if kind >= len(counts):
                raise ValueError("Unsupported ICC parametric curve")
            return {"kind": "parametric", "function": kind, "parameters": fixed(block, 12, counts[kind])}
        if block[:4] == b"curv":
            n = struct.unpack_from(">I", block, 8)[0]
            if n == 0:
                return {"kind": "gamma", "gamma": 1.0}
            if n == 1:
                return {"kind": "gamma", "gamma": struct.unpack_from(">H", block, 12)[0] / 256}
            return {"kind": "table", "values": (np.frombuffer(block, dtype=">u2", count=n, offset=12) / 65535).tolist()}
        raise ValueError("Unsupported ICC transfer curve")
    try:
        columns = []
        for key in (b"rXYZ", b"gXYZ", b"bXYZ"):
            if tags[key][:4] != b"XYZ ":
                raise ValueError("Invalid ICC primary tag")
            columns.append(fixed(tags[key], 8, 3))
        curves = tuple(curve(tags[key]) for key in (b"rTRC", b"gTRC", b"bTRC"))
    except KeyError as exc:
        raise ValueError("ICC matrix/TRC tags are missing") from exc
    return RgbProfile("embedded RGB matrix/TRC", hashlib.sha256(data).hexdigest(), np.array(columns).T, curves)


def embedded_icc(path: Path) -> bytes:
    if path.suffix.lower() in (".ppm", ".pnm"):
        return path.with_suffix(".icc").read_bytes()
    with Image.open(path) as image:
        data = image.info.get("icc_profile")
    if not data:
        raise ValueError(f"Missing ICC profile: {path}")
    return data


def image_profile(path: Path) -> RgbProfile:
    return profile_from_icc(embedded_icc(path))


def lab_from_linear(values: np.ndarray, profile: RgbProfile) -> np.ndarray:
    xyz = np.asarray(values, dtype=np.float64) @ profile.matrix.T / D50
    delta = 6 / 29
    f = np.where(xyz > delta ** 3, np.cbrt(xyz), xyz / (3 * delta ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)
