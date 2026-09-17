"""Export full-frame navigation images independently of measured native crops.

One bounded, low-priority decode at a time. Hash-bound linear-light reductions
are cached outside the site so restarting never requires re-encoding a JXL.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import numpy as np
from PIL import Image, ImageCms, ImageDraw
from break_even_image_tools import read_rgb_image
from image_color import image_profile, profile_from_icc, decode_curve
from incremental_cache import atomic_write_json, fingerprint, sha256_file
from rebuild_verified_report import atomic_bytes, check_resources, close_image, run, LEVELS
from report_transforms import MODES, transform

MAX_DIM = 640


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def reduce_full_frame(encoded, profile, max_dim=MAX_DIM):
    """Box-average every input pixel, including the bottom and right edges.

    Integer input permits small exact TRC lookup tables. Each working buffer
    holds only one output row's input band and one channel.
    """
    h, w = encoded.shape[:2]
    scale = min(1, max_dim / max(h, w))
    oh, ow = max(1, round(h * scale)), max(1, round(w * scale))
    xs = np.linspace(0, w, ow + 1, dtype=int)
    ys = np.linspace(0, h, oh + 1, dtype=int)
    codes = np.arange(65536, dtype=np.float64) / 65535
    tables = [decode_curve(codes, c).astype(np.float32) for c in profile.curves]
    result = np.empty((oh, ow, 3), np.float32)
    for y, (top, bottom) in enumerate(zip(ys[:-1], ys[1:])):
        for c, table in enumerate(tables):
            values = table[encoded[top:bottom, :, c]]
            columns = values.mean(axis=0, dtype=np.float64)
            result[y, :, c] = np.add.reduceat(columns, xs[:-1]) / np.diff(xs)
    return result


def crop_on_source(xywh, reference_shape, source_shape, shift=(0, 0)):
    x, y, w, h = xywh
    sx, sy = source_shape[1] / reference_shape[1], source_shape[0] / reference_shape[0]
    return [(x - shift[0]) * sx, (y - shift[1]) * sy, w * sx, h * sy]


def save_overview(path, linear, profile, mode, recipe, source_shape, crop):
    rgb = np.rint(np.clip(profile.display(transform(linear, mode, recipe)), 0, 1) * 255).astype(np.uint8)
    image = Image.fromarray(rgb)
    sx, sy = image.width / source_shape[1], image.height / source_shape[0]
    x, y, w, h = crop
    rect = (round(x*sx), round(y*sy), round((x+w)*sx), round((y+h)*sy))
    draw = ImageDraw.Draw(image)
    draw.rectangle(tuple(v+d for v, d in zip(rect, (-1, -1, 1, 1))), outline="black", width=4)
    draw.rectangle(rect, outline=(255, 212, 0), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=90, method=4,
               icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    atomic_bytes(path, buffer.getvalue())
    return [image.width, image.height]


def reduced_source(saved, reference_profile, args, cache_code, decoder=False):
    source = Path(saved["path"])
    if sha256_file(source) != saved["sha256"]:
        raise ValueError("Overview source differs from the audited file: " + source.name)
    key = fingerprint({"source": saved["sha256"], "code": cache_code,
                       "reference_icc": reference_profile.sha256, "decoder": decoder, "max_dim": MAX_DIM})
    cached = args.scratch / (key + ".npy")
    receipt = cached.with_suffix(".json")
    if cached.is_file() and receipt.is_file():
        record = read(receipt)
        if sha256_file(cached) == record["sha256"]:
            return np.load(cached, allow_pickle=False), record
    check_resources(args.scratch)
    ppm, icc = args.scratch / "decode.ppm", args.scratch / "decode.icc"
    try:
        if decoder:
            # libjxl's progressive downsampling may retain full output dimensions;
            # always reduce the actual returned image and verify its coverage.
            run([str(args.djxl), str(source), str(ppm), "--bits_per_sample=16",
                 "--downsampling=8", "--num_threads=4", "--icc_out="+str(icc)])
            profile = profile_from_icc(icc.read_bytes())
            pixels = read_rgb_image(ppm)
        else:
            profile = reference_profile if source.suffix.lower() == ".ppm" else image_profile(source)
            pixels = read_rgb_image(source)
        try:
            shape = list(pixels.shape)
            if pixels.dtype.kind != "u" or pixels.dtype.itemsize != 2:
                raise ValueError("Overview input must be RGB16")
            linear = reduce_full_frame(pixels, profile)
        finally:
            close_image(pixels)
        linear = (linear @ (np.linalg.inv(reference_profile.matrix) @ profile.matrix).T).astype(np.float32)
        buffer = io.BytesIO(); np.save(buffer, linear, allow_pickle=False)
        atomic_bytes(cached, buffer.getvalue())
        record = {"sha256": sha256_file(cached), "source_sha256": saved["sha256"],
                  "source_shape": shape, "icc_sha256": profile.sha256,
                  "source_bounds": [0, 0, shape[1], shape[0]]}
        atomic_write_json(receipt, record)
        return linear, record
    finally:
        ppm.unlink(missing_ok=True); icc.unlink(missing_ok=True)


def build(args):
    args.scratch.mkdir(parents=True, exist_ok=True)
    environment = read(args.results / "environment.json")
    if sha256_file(args.djxl) != environment["tools"]["djxl.exe"]:
        raise ValueError("Use the pinned, audited JPEG XL decoder")
    code_paths = ("scripts/build_verified_overviews.py", "src/report_transforms.py", "src/image_color.py",
                  "src/break_even_image_tools.py", "scripts/rebuild_verified_report.py")
    code = {p: sha256_file(ROOT / p) for p in code_paths}
    records, assets = [], {}
    frames = read(args.results / "private_inventory.json")["frames"]
    if args.case:
        frames = [f for f in frames if f["set_id"] in args.case]
    for frame in frames:
        directory = args.results / frame["slug"] / frame["set_id"]
        audit = read(directory / "source_audit.json")
        profile = image_profile(Path(frame["source_render"]))
        if profile.recipe() != audit["profile"]:
            raise ValueError("Reference ICC changed")
        checkpoints = {level: read(directory / (level + ".json")) for level in LEVELS}
        recipe = checkpoints[LEVELS[0]]["analysis_recipe"]
        broad = next(s for s in recipe["scopes"] if s["kind"] != "native_crop")
        ba = broad["alignment"]
        global_shift = [ba["shift_x_px"] * 10, ba["shift_y_px"] * 10] if ba["applied"] else [0, 0]
        crop_records = []
        for crop in frame["crops"]:
            metadata = read(crop["metadata"])
            crop_records.append({"scan_set": frame["scan_set"], "set_id": frame["set_id"],
                                 "crop": crop["name"], "crop_xywh": crop["xywh"],
                                 "reference_shape": audit["shape"],
                                 "recipe_sha256": fingerprint(metadata["browser_transform_recipe"]), "sources": {}})
        sources = {"reference": audit["reference_state"], "raw61": audit["raw_render_state"],
                   **{"jxl_"+k: v["audit"]["released"] for k, v in checkpoints.items()}}
        for role, saved in sources.items():
            print("OVERVIEW", frame["set_id"], role, flush=True)
            linear, source_record = reduced_source(saved, profile, args, code, role.startswith("jxl_"))
            if role != "raw61" and source_record["source_shape"] != audit["shape"]:
                raise ValueError("Overview does not cover the complete PS16 frame")
            for crop, record in zip(frame["crops"], crop_records):
                metadata = read(crop["metadata"])
                alignment = metadata["local_raw61_alignment"]
                shift = [global_shift[i] + (alignment[k] if alignment["applied"] else 0)
                         for i, k in enumerate(("shift_x_px", "shift_y_px"))] if role == "raw61" else [0, 0]
                box = crop_on_source(crop["xywh"], audit["shape"], source_record["source_shape"], shift)
                files = {}
                for mode in MODES:
                    relative = f"assets/overviews-verified/{frame['slug']}/{frame['set_id']}/{crop['name']}/{role}_{mode}.webp"
                    size = save_overview(args.site / relative, linear, profile, mode,
                                         metadata["browser_transform_recipe"], source_record["source_shape"], box)
                    files[mode] = relative
                    assets[relative] = sha256_file(args.site / relative)
                record["sources"][role] = {k: v for k, v in source_record.items() if k != "sha256"}
                record["sources"][role].update({"files": files, "size": size, "crop_xywh": box})
            del linear
        records.extend(crop_records)
    payload = {"schema": 3, "method": "Full-frame RGB16 sources, ICC-linear box reduction covering every pixel, shared native-crop tone recipes, sRGB WebP navigation images with crop outlines",
               "decoder_downsampling_requested": 8, "decoder_sha256": sha256_file(args.djxl),
               "recipe_code": code, "records": records, "asset_hashes": assets}
    payload["evidence_id"] = "overviews-" + fingerprint(payload)[:16]
    destination = args.site / "data" / ("overview-pilot.json" if args.case else "overview-evidence.json")
    atomic_write_json(destination, payload)
    print("EXPORTED", len(records), "crops;", len(assets), "full-frame overviews", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, default=ROOT / "results/verified_report")
    p.add_argument("--site", type=Path, default=ROOT / "site")
    p.add_argument("--scratch", type=Path, required=True)
    p.add_argument("--djxl", type=Path, required=True)
    p.add_argument("--case", action="append")
    build(p.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
