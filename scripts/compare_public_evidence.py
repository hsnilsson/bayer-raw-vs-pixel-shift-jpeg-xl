"""Compare independently reproduced public measurements, ignoring ICC timestamps."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def compare(expected, actual):
    """Require the same experiment and numerical values within roundoff tolerance."""
    for key in ("schema", "recipe_code", "tools", "versions"):
        if expected[key] != actual[key]:
            raise ValueError(f"Different public experiment: {key}")
    left = {r["public_input"]: r for r in expected["records"]}
    right = {r["public_input"]: r for r in actual["records"]}
    if left.keys() != right.keys() or len(left) != 6:
        raise ValueError("Public source coverage changed")
    values = 0
    max_absolute_error = 0.0
    byte_differences = []

    def equal(a, b, label):
        nonlocal values, max_absolute_error
        if isinstance(a, dict):
            if not isinstance(b, dict) or a.keys() != b.keys():
                raise ValueError(f"Different fields: {label}")
            for key in a:
                equal(a[key], b[key], f"{label}.{key}")
        elif isinstance(a, list):
            if not isinstance(b, list) or len(a) != len(b):
                raise ValueError(f"Different list: {label}")
            for i, (x, y) in enumerate(zip(a, b)):
                equal(x, y, f"{label}[{i}]")
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            if not isinstance(b, (int, float)) or not math.isfinite(a) or not math.isfinite(b):
                raise ValueError(f"Invalid numeric value: {label}")
            if not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(f"Different measurement: {label}: {a} vs {b}")
            values += 1
            max_absolute_error = max(max_absolute_error, abs(a - b))
        elif a != b:
            raise ValueError(f"Different value: {label}")

    def profile(value):
        # ICC headers can contain creation time. The full transform must match.
        return {k: v for k, v in value.items() if k != "icc_sha256"}

    for name, a in left.items():
        b = right[name]
        for key in ("source_sha256", "source_profile_sha256", "source_shape", "crop_xywh", "conversion", "source_provenance"):
            equal(a[key], b[key], f"{name}.{key}")
        equal(profile(a["working_profile"]), profile(b["working_profile"]), f"{name}.working_profile")
        ar, br = dict(a["recipe"]), dict(b["recipe"])
        ar["profile"], br["profile"] = profile(ar["profile"]), profile(br["profile"])
        equal(ar, br, f"{name}.recipe")
        if len(a["levels"]) != 4 or len(b["levels"]) != 4:
            raise ValueError("Public distance coverage changed")
        for x, y in zip(a["levels"], b["levels"]):
            for key in ("distance", "pixel_exact", "measurements"):
                equal(x[key], y[key], f"{name}.d{x['distance']}.{key}")
            if x["encoded_bytes"] != y["encoded_bytes"]:
                if a["working_profile"]["icc_sha256"] == b["working_profile"]["icc_sha256"]:
                    raise ValueError(f"Encoded size changed with identical input/profile: {name}")
                byte_differences.append({"source": name, "distance": x["distance"],
                                         "expected": x["encoded_bytes"], "actual": y["encoded_bytes"]})
            equal(profile(x["decoded_profile"]), profile(y["decoded_profile"]), f"{name}.decoded_profile")
        if not a["levels"][0]["pixel_exact"] or not b["levels"][0]["pixel_exact"]:
            raise ValueError("Lossless public control is not exact")
    return {"sources": 6, "candidates": 24, "transform_measurements": 120,
            "compared_numeric_values": values, "max_absolute_error": max_absolute_error,
            "runtime_profile_encoded_byte_differences": byte_differences,
            "relative_tolerance": 1e-10, "absolute_tolerance": 1e-12}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(*(json.loads(p.read_text(encoding="utf-8")) for p in (args.expected, args.actual))), indent=2))
