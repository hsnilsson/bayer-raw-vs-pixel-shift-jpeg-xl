"""Refine declared native RAW baselines and remeasure verified decoded crops.

Run after run_verified_rebuild.py and before auxiliary evidence/finalization.
The core analysis environment remains frozen. The additional scientific code,
selection and parameters are bound separately in each affected analysis recipe.
Whole-frame measurements are reused only when their complete scope is identical.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import numpy as np
from break_even_image_tools import read_rgb_image
from image_color import RgbProfile
from incremental_cache import atomic_write_json, fingerprint, sha256_file
from native_registration import provenance, selected, refine
from preview_cache import preserve_equivalent_png
from report_transforms import measure, recipe_for, MODES
import rebuild_verified_report as engine


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def retained_pixels(results, item, asset):
    expected = asset.get("decoded_sha256", asset["sha256"])
    path = Path(item["metadata"]).parent / asset["file"].removesuffix(".gz")
    if not path.is_file():
        path = results / "viewer-pixels" / (expected + ".rgb16le")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Retained decoded crop changed")
    w, h = item["xywh"][2:]
    return np.frombuffer(data, dtype="<u2").reshape(h, w, 3)


def process(frame, results):
    names = selected(ROOT, frame)
    if not names:
        return
    if set(names) != {c["name"] for c in frame["crops"]}:
        raise ValueError("This stage requires the complete native crop set for a selected frame")
    directory = results / frame["slug"] / frame["set_id"]
    records = {level: read(directory / (level + ".json")) for level in engine.LEVELS}
    complete = read(directory / "complete.json")
    extension = provenance(ROOT)
    # An unchanged second run must not rewrite images or expensive measurements.
    if (all(r["analysis_recipe"].get("native_registration") == extension for r in records.values())
            and all(sha256_file(ROOT / p) == h for p, h in complete["metadata_hashes"].items())
            and all((ROOT / p).is_file() and sha256_file(ROOT / p) == h
                    for r in records.values() for p, h in r["asset_hashes"].items())):
        print("REUSE NATIVE REGISTRATION", frame["set_id"], flush=True)
        return
    engine.check_resources(results, 1)
    audit = read(directory / "source_audit.json")
    environment = read(results / "environment.json")
    for path, digest in environment["code"].items():
        if sha256_file(ROOT / path) != digest:
            raise ValueError("Frozen analysis engine changed")
    import PIL, tifffile, imagecodecs, os
    runtime = {"python": sys.version, "numpy": np.__version__, "Pillow": PIL.__version__,
               "tifffile": tifffile.__version__, "imagecodecs": imagecodecs.__version__}
    if runtime != environment["runtime"] or os.environ.get("OPENBLAS_NUM_THREADS") != "1":
        raise ValueError("Use the pinned numerical environment and responsive launcher")
    for role in ("reference", "source_render", "raw_render"):
        if sha256_file(Path(frame[role])) != audit[role + "_state"]["sha256"]:
            raise ValueError("Registration source differs from the audited render")
    for record in records.values():
        if record["analysis_recipe"]["code"] != fingerprint(environment):
            raise ValueError("Mixed core analysis environments")
        for item in frame["crops"]:
            retained_pixels(results, item, record["viewer_assets"][item["name"]])
    print("REFINE NATIVE REGISTRATION", frame["set_id"], flush=True)
    profile, scopes = engine.prepare_scopes(audit | {"crops": frame["crops"]})
    fields = ("name", "kind", "factor", "input_bounds", "alignment", "recipe")
    broad = {k: scopes[0][k] for k in fields}
    if any(r["analysis_recipe"]["scopes"][0] != broad for r in records.values()):
        raise ValueError("Whole-frame scope changed; a full engine rebuild is required")
    ba = scopes[0]["alignment"]
    global_shift = (ba["shift_x_px"] * 10, ba["shift_y_px"] * 10) if ba["applied"] else (0, 0)
    raw = read_rgb_image(Path(frame["raw_render"]))
    try:
        for scope in scopes[1:]:
            start = time.monotonic()
            aligned, alignment = refine(scope["reference"], scope["raw"], raw, profile,
                                         tuple(scope["input_bounds"]), tuple(audit["shape"]),
                                         global_shift, scope["alignment"])
            scope.update(raw=aligned, encoded_raw=profile.encode_u16(aligned), alignment=alignment)
            valid = engine.scope_slice(scope["reference"], alignment)
            scope["recipe"] = recipe_for(valid, profile)
            scope["raw_metrics"] = measure(valid, engine.scope_slice(aligned, alignment), profile, scope["recipe"])
            scope["refinement_seconds"] = time.monotonic() - start
            print(scope["name"], alignment, flush=True)
    finally:
        engine.close_image(raw)
    recipe = copy.deepcopy(next(iter(records.values()))["analysis_recipe"])
    recipe.update(scopes=[{k: s[k] for k in fields} for s in scopes], native_registration=extension)
    recipe_hash = fingerprint(recipe)
    for s in scopes[1:]:
        s["assets"] = {"reference": engine.export_scope(s, "reference", s["encoded_reference"], s["reference"], profile),
                       "raw61": engine.export_scope(s, "raw61", s["encoded_raw"], s["raw"], profile)}
    for level, record in records.items():
        start = time.monotonic()
        # No new JPEG XL decode or encode: these hash-verified RGB16 samples are
        # exactly the crops from the prior full decode, with their actual ICC.
        rows = [m for m in record["measurements"] if m["scope"] == "full_frame_box10"]
        hashes = {}
        for s in scopes[1:]:
            asset = record["viewer_assets"][s["name"]]
            encoded = retained_pixels(results, s["item"], asset)
            p = asset["profile"]
            decoded_profile = RgbProfile(p["name"], p["icc_sha256"], np.asarray(p["rgb_to_xyz_d50"]), tuple(p["curves"]))
            linear = (decoded_profile.linearize(encoded) @ np.asarray(p["linear_to_reference"]).T).astype(np.float32)
            measured = measure(engine.scope_slice(s["reference"], s["alignment"]),
                               engine.scope_slice(linear, s["alignment"]), profile, s["recipe"])
            rows.extend({"scope": s["name"], "scope_kind": s["kind"], "scale": 1,
                         "alignment": s["alignment"], "input_bounds": s["input_bounds"],
                         "candidate": m, "raw61": r} for m, r in zip(measured, s["raw_metrics"]))
            new_asset = engine.export_scope(s, "jxl_" + level, encoded, linear, profile, decoded_profile)
            if new_asset["sha256"] != asset["sha256"]:
                raise ValueError("Candidate RGB16 codes changed during registration refinement")
            s["assets"]["jxl_" + level] = new_asset
            record["viewer_assets"][s["name"]] = new_asset
            path = Path(s["item"]["metadata"]).parent
            for key in ("reference", "raw61", "jxl_" + level):
                for payload in [path / (key + ".rgb16le"), *path.glob("preview_*_" + key + ".png")]:
                    hashes[payload.relative_to(ROOT).as_posix()] = sha256_file(payload)
        record.update(analysis_recipe=recipe, measurements=rows, asset_hashes=hashes,
                      fingerprint=fingerprint({"recipe": recipe_hash, "candidate": record["audit"]["released"]["sha256"]}),
                      native_registration_seconds=time.monotonic()-start + sum(s["refinement_seconds"] for s in scopes[1:])/len(records))
        atomic_write_json(directory / (level + ".json"), record)
        print("REMEASURED", frame["set_id"], level, flush=True)
    for s in scopes[1:]:
        path = Path(s["item"]["metadata"])
        meta = read(path)
        meta.update(analysis_recipe_sha256=recipe_hash, local_raw61_alignment=s["alignment"],
                    browser_transform_recipe=s["recipe"], asset_manifest=s["assets"])
        meta["build_inputs"]["recipe_sha256"] = recipe_hash
        meta["rgb16"]["sources"] = {k: v["file"] for k, v in s["assets"].items()}
        meta["rgb16"]["sources"]["ps16_lossless"] = "reference.rgb16le"
        atomic_write_json(path, meta)
        complete["metadata_hashes"][path.relative_to(ROOT).as_posix()] = sha256_file(path)
    complete.pop("metadata_export", None)
    atomic_write_json(directory / "complete.json", complete)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/verified_report")
    args = parser.parse_args()
    engine.atomic_bytes = preserve_equivalent_png(engine.atomic_bytes)
    for frame in read(args.results / "private_inventory.json")["frames"]:
        process(frame, args.results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
