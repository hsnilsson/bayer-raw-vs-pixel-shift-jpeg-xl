"""Preserve byte identity when a PNG export changes only its ICC creation date.

This is an output-transport policy. Pixel calculation and the scientific
measurement engine remain unchanged. Changed pixels or profile data are never
accepted as equivalent.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def comparable_info(info):
    result = dict(info)
    icc = result.get("icc_profile")
    if isinstance(icc, bytes) and len(icc) >= 128:
        result["icc_profile"] = icc[:24] + bytes(12) + icc[36:]
    return result


def equivalent_png(first: bytes, second: bytes) -> bool:
    if first == second:
        return True
    try:
        # Verify the existing file before retaining its bytes.
        with Image.open(io.BytesIO(first)) as old:
            old.verify()
        with Image.open(io.BytesIO(first)) as old, Image.open(io.BytesIO(second)) as new:
            return (old.format == new.format == "PNG" and old.mode == new.mode
                    and old.size == new.size and comparable_info(old.info) == comparable_info(new.info)
                    and old.tobytes() == new.tobytes())
    except (OSError, ValueError):
        return False


def preserve_equivalent_png(writer):
    """Compose an atomic writer with exact-pixel/profile preview reuse."""
    def write(path: Path, data: bytes):
        path = Path(path)
        if path.suffix.lower() == ".png" and path.is_file():
            if equivalent_png(path.read_bytes(), data):
                return
        writer(path, data)
    return write
