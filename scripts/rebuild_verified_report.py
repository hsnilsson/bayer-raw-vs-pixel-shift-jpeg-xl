"""Audited, resumable, one-decode-per-candidate public-report rebuild.

Private paths live only in the local inventory/checkpoints. Publication receives
content hashes, crop coordinates, measurements and small approved derivatives.
Run --help for the staged audit, pilot and complete workflow.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import numpy as np
from PIL import Image, ImageCms
from break_even_image_tools import read_rgb_image, crop
from image_color import image_profile, embedded_icc, profile_from_icc, decode_curve
from incremental_cache import sha256_file, fingerprint, atomic_write_json
from report_transforms import MODES, recipe_for, transform, measure, reduce_linear, resize_linear, sample_raw_crop, align_scope
from run_local_scan_study import slugify

TAGS = ["Make", "Model", "Orientation", "LensMake", "LensModel", "LensInfo", "FocalLength", "FNumber",
        "ExposureTime", "ISO", "DateTimeOriginal", "EXIF:CreateDate", "XMP:CreateDate",
        "SubSecTimeOriginal", "SubSecTimeDigitized", "Artist", "Copyright", "ImageDescription"]
LEVELS = ["d003", "d005", "d010", "d020", "d022", "d025", "d028", "d030", "d100", "d200"]
TOOL_RUNS = []


def run(command: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    kwargs = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else {}
    start = time.monotonic()
    peak = [0]
    stopped = threading.Event()
    with subprocess.Popen(list(map(str,command)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs) as process:
        def sample_memory():
            if os.name != "nt": return
            class Counters(ctypes.Structure):
                _fields_ = [("cb",ctypes.c_ulong),("faults",ctypes.c_ulong)] + [(n,ctypes.c_size_t) for n in
                            ("peak","working","pool_peak","pool","nonpool_peak","nonpool","pagefile","peak_pagefile")]
            c = Counters(); c.cb = ctypes.sizeof(c)
            while not stopped.wait(.1):
                if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(int(process._handle)),ctypes.byref(c),c.cb):
                    peak[0] = max(peak[0],c.peak)
        watcher = threading.Thread(target=sample_memory,daemon=True); watcher.start()
        try:
            out,err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise
        finally:
            stopped.set(); watcher.join()
        result = subprocess.CompletedProcess(command,process.returncode,out,err)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}): {result.stderr.decode(errors='replace')[-4000:]}")
    duration = time.monotonic()-start
    TOOL_RUNS.append({"tool":Path(command[0]).name,"seconds":duration,"sampled_peak_working_bytes":peak[0]})
    print(f"  {Path(command[0]).name}: {duration:.1f}s, sampled peak {peak[0]/2**20:.0f} MiB", flush=True)
    return result


def check_resources(scratch: Path, required_gib: float = 3) -> None:
    if shutil.disk_usage(scratch).free < (20 + required_gib) * 2**30:
        raise RuntimeError("Resumable pause: scratch disk below 20 GiB reserve plus next-job allowance")
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                        ("total", "available", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]
        m = Memory(); m.length = ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            raise OSError("Cannot check available RAM")
        if m.available < (8 + required_gib) * 2**30:
            raise RuntimeError(f"Resumable pause: {m.available/2**30:.1f} GiB RAM available; need 8 GiB reserve + {required_gib:g} GiB")


def close_image(arr: np.ndarray) -> None:
    mmap = getattr(arr, "_mmap", None)
    if mmap is not None:
        mmap.close()


def state(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def metadata(exiftool: str, path: Path, extra: list[str] = []) -> dict:
    row = json.loads(run([exiftool, "-j", "-G1", *["-"+t for t in TAGS + extra], str(path)], 120).stdout)[0]
    row.pop("SourceFile", None)
    return row


def source_inventory(args: argparse.Namespace) -> list[dict]:
    manifests = {}
    for file in (args.archive / "input").glob("*/scan_manifest.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        manifests[slugify(data.get("scan_root_name", file.parent.name))] = (file, data)
    frames = {}
    for file in sorted((ROOT / "site/assets/review-viewers").rglob("metadata.json")):
        old = json.loads(file.read_text(encoding="utf-8"))
        scan, frame = slugify(old["scan_set"]), old["set_id"]
        if args.case and frame not in args.case:
            continue
        if (scan, frame) not in frames:
            manifest_path, manifest = manifests[scan]
            capture = next(c for c in manifest["capture_sets"] if c["set_id"] == frame)
            raw_source = capture.get("single_raw")
            cohort = "primary_compressed_independent"
            if not raw_source:
                raw_source = manifest["raw_pixelshift_groups"][0]["raw_files"][0]
                cohort = "secondary_same_sequence_target"
            elif frame == "_DSC6598":
                cohort = "diagnostic_flat_field"
            src = old["build_inputs"]["sources"]
            def resolve(s):
                p = Path(s["path"])
                if not p.is_absolute() and frame == "_DSC0001-_DSC0016" and args.f45_root:
                    return args.f45_root / p.relative_to("outputs")
                return p if p.is_absolute() else args.archive / p
            ref = resolve(src["ps16"])
            render_root = "rawtherapee_renders_f45" if frame == "_DSC0001-_DSC0016" else "rawtherapee_renders"
            render = args.archive / "outputs" / render_root / scan / frame / "ps16.tif"
            if frame == "_DSC0001-_DSC0016" and args.f45_root:
                render = args.f45_root / render_root / scan / frame / "ps16.tif"
            raw_render = render.with_name("raw61.tif")
            frames[(scan, frame)] = {"scan_set": old["scan_set"], "slug": scan, "set_id": frame,
                "cohort": cohort, "source_manifest": str(manifest_path), "source_capture": capture,
                "raw_source": str(manifest_path.parent / raw_source),
                "dng_source": str(manifest_path.parent / capture["pixelshift16_dng"]),
                "reference": str(ref), "source_render": str(render), "raw_render": str(raw_render),
                "candidates": {k: str(resolve(v)) for k,v in src["jxl"].items()}, "crops": []}
        frames[(scan,frame)]["crops"].append({"name": old["crop_name"], "xywh": old["crop"],
                                             "metadata": str(file), "old_metadata": old})
    return list(frames.values())


def verify_references(frame: dict, args: argparse.Namespace) -> dict:
    print(f"AUDIT {frame['slug']}/{frame['set_id']}", flush=True)
    for key in ("raw_source", "dng_source", "reference", "source_render", "raw_render"):
        path = Path(frame[key])
        if not path.is_file():
            raise FileNotFoundError(path)
        frame[key + "_state"] = state(path)
    raw_info = metadata(args.exiftool, Path(frame["raw_source"]), ["SonyRawFileType", "Compression", "PixelShiftInfo"])
    frame["capture_metadata"] = raw_info
    if frame["cohort"] == "primary_compressed_independent":
        capture_tags = {k.split(":")[-1]:v for k,v in raw_info.items()}
        if capture_tags.get("SonyRawFileType") != "Sony Compressed RAW" or capture_tags.get("PixelShiftInfo") not in (None, "n/a"):
            frame["cohort"] = "secondary_sequence_or_uncompressed"
    profile = image_profile(Path(frame["source_render"]))
    verify_profile(embedded_icc(Path(frame["reference"])), embedded_icc(Path(frame["source_render"])))
    raw_profile = image_profile(Path(frame["raw_render"]))
    if profile.sha256 != raw_profile.sha256:
        raise ValueError("Source RAW61 and PS16 render profiles differ; explicit conversion required")
    frame["profile"] = profile.recipe()
    reference = read_rgb_image(Path(frame["reference"]))
    render = read_rgb_image(Path(frame["source_render"]))
    try:
        if reference.shape != render.shape or reference.dtype.itemsize != 2 or render.dtype.itemsize != 2:
            raise ValueError("Reference dimensions/precision differ from source render")
        for y in range(0, reference.shape[0], 64):
            if not np.array_equal(reference[y:y+64], render[y:y+64]):
                raise ValueError(f"Legacy reference does not match retained source render at row {y}")
        frame["shape"] = list(reference.shape)
        frame["reference_pixel_identity"] = True
        # Independent LittleCMS oracle on real profile and color samples.
        sample = reference[::257, ::257].astype(np.float64) / 65535
        u8 = np.rint(sample * 255).astype(np.uint8)
        oracle = np.asarray(ImageCms.profileToProfile(Image.fromarray(u8),
                ImageCms.ImageCmsProfile(__import__('io').BytesIO(embedded_icc(Path(frame["source_render"])))),
                ImageCms.createProfile("sRGB"), outputMode="RGB", renderingIntent=1))
        actual = np.rint(np.clip(profile.display(profile.linearize(u8)),0,1)*255)
        error = float(np.max(np.abs(actual-oracle)))
        if error > 2:
            raise ValueError(f"ICC conversion differs from LittleCMS by {error} display codes")
        frame["littlecms_max_display_code_error"] = error
    finally:
        close_image(reference); close_image(render)
    frame["render_metadata"] = metadata(args.exiftool, Path(frame["source_render"]))
    return frame


def lossless_gate(frame: dict, args: argparse.Namespace) -> dict:
    """Real RGB16 crop, ICC and photographic metadata round-trip pilot."""
    directory = args.scratch / "lossless-pilot" / frame["set_id"]
    directory.mkdir(parents=True, exist_ok=True)
    image = read_rgb_image(Path(frame["reference"]))
    x,y,_,_ = frame["crops"][0]["xywh"]
    sample = np.array(image[y:y+256,x:x+256], dtype=np.uint16)
    close_image(image)
    source, encoded, decoded = directory/"source.ppm", directory/"lossless.jxl", directory/"decoded.ppm"
    icc, out_icc = directory/"source.icc", directory/"decoded.icc"
    source.write_bytes(b"P6\n256 256\n65535\n" + sample.astype(">u2").tobytes())
    icc.write_bytes(embedded_icc(Path(frame["source_render"])))
    run([str(args.tools/"cjxl.exe"),str(source),str(encoded),"--container=1","-x",f"icc_pathname={icc}","-e","7","-d","0","--num_threads=4"],120)
    run([args.exiftool,"-overwrite_original","-TagsFromFile",frame["source_render"],*["-"+t for t in frame["render_metadata"]],str(encoded)],120)
    actual_metadata = metadata(args.exiftool,encoded)
    if any(actual_metadata.get(k) != v for k,v in frame["render_metadata"].items()):
        raise ValueError("Lossless pilot metadata mismatch")
    run([str(args.tools/"djxl.exe"),str(encoded),str(decoded),"--bits_per_sample=16","--num_threads=4",f"--icc_out={out_icc}"],120)
    actual = read_rgb_image(decoded)
    try:
        if not np.array_equal(actual,sample):
            raise ValueError("Lossless real-image pilot changed pixels")
    finally:
        close_image(actual)
    verify_profile(out_icc.read_bytes(),icc.read_bytes())
    return {"pixel_exact":True,"icc_equivalent":True,"metadata_exact":True,"crop":[x,y,256,256],"encoded_sha256":sha256_file(encoded)}


def verify_profile(actual: bytes, expected: bytes) -> None:
    a, b = profile_from_icc(actual), profile_from_icc(expected)
    np.testing.assert_allclose(a.matrix, b.matrix, atol=3e-5, rtol=0)
    x = np.linspace(0, 1, 4097)
    for ac, bc in zip(a.curves, b.curves):
        np.testing.assert_allclose(decode_curve(x, ac), decode_curve(x, bc), atol=3e-5, rtol=0)


def prepare_candidate(frame: dict, level: str, args: argparse.Namespace) -> tuple[Path, dict]:
    original = Path(frame["candidates"][level])
    original_state = state(original)
    expected = frame["render_metadata"]
    actual = metadata(args.exiftool, original)
    changes = {k: {"expected": v, "actual": actual.get(k)} for k,v in expected.items() if actual.get(k) != v}
    candidate = original
    if changes:
        candidate = args.scratch / "repaired-metadata" / frame["slug"] / frame["set_id"] / level / "ps16.jxl"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        partial = candidate.with_suffix(".partial.jxl")
        shutil.copyfile(original, partial)
        run([args.exiftool, "-m", "-overwrite_original", "-TagsFromFile", frame["source_render"],
             *["-"+t for t in expected], str(partial)], 120)
        actual = metadata(args.exiftool, partial)
        if any(actual.get(k) != v for k,v in expected.items()):
            raise ValueError(f"Metadata repair did not reproduce source tags: {level}")
        os.replace(partial, candidate)
    header = run([str(args.tools / "jxlinfo.exe"), "-v", str(candidate)], 120).stdout.decode(errors="replace")
    w, h = frame["shape"][1], frame["shape"][0]
    if f"{w}x{h}" not in header or "16-bit" not in header:
        raise ValueError(f"Candidate header is not expected RGB16 {w}x{h}: {header}")
    return candidate, {"original": original_state, "released": state(candidate), "metadata_pass": True,
                        "repaired_fields": sorted(changes), "header": header}


def scope_slice(array: np.ndarray, alignment: dict) -> np.ndarray:
    x,y,w,h = alignment["valid_xywh"]
    return array[y:y+h, x:x+w]


def prepare_scopes(frame: dict) -> tuple[object, list[dict]]:
    profile = image_profile(Path(frame["source_render"]))
    ref = read_rgb_image(Path(frame["reference"]))
    raw = read_rgb_image(Path(frame["raw_render"]))
    try:
        broad = reduce_linear(ref, profile, 10)
        raw_broad = reduce_linear(raw, profile, 5)
        raw_broad = resize_linear(raw_broad, (broad.shape[1], broad.shape[0]))
        aligned_broad, alignment = align_scope(broad, raw_broad, profile, 8)
        global_shift = (alignment["shift_x_px"]*10, alignment["shift_y_px"]*10) if alignment["applied"] else (0,0)
        scopes = [{"name": "full_frame_box10", "kind": "reduced_full_frame", "factor": 10,
                   "reference": broad, "raw": aligned_broad, "alignment": alignment,
                   "input_bounds": [0,0,broad.shape[1]*10,broad.shape[0]*10]}]
        for item in frame["crops"]:
            encoded = crop(ref, ",".join(map(str,item["xywh"])))
            linear = profile.linearize(encoded)
            raw_linear = sample_raw_crop(raw, profile, tuple(item["xywh"]), tuple(ref.shape), global_shift)
            aligned, local = align_scope(linear, raw_linear, profile, 32)
            scopes.append({"name": item["name"], "kind": "native_crop", "factor": 1,
                           "reference": linear, "raw": aligned, "encoded_reference": encoded,
                           "encoded_raw": profile.encode_u16(aligned), "alignment": local,
                           "input_bounds": item["xywh"], "item": item})
        for scope in scopes:
            valid_ref = scope_slice(scope["reference"], scope["alignment"])
            scope["recipe"] = recipe_for(valid_ref, profile)
            scope["raw_metrics"] = measure(valid_ref, scope_slice(scope["raw"],scope["alignment"]), profile, scope["recipe"])
        return profile, scopes
    finally:
        close_image(ref); close_image(raw)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)


def write_preview(path: Path, linear: np.ndarray, profile, max_dim=360) -> None:
    image = Image.fromarray(np.rint(np.clip(profile.display(linear),0,1)*255).astype(np.uint8))
    image.thumbnail((max_dim,max_dim), Image.Resampling.LANCZOS)
    import io
    buffer = io.BytesIO(); image.save(buffer, format="PNG", icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    atomic_bytes(path, buffer.getvalue())


def export_scope(scope: dict, source_key: str, encoded: np.ndarray, linear: np.ndarray, profile, input_profile=None) -> dict:
    directory = Path(scope["item"]["metadata"]).parent
    filename = source_key + ".rgb16le"
    atomic_bytes(directory / filename, np.asarray(encoded, dtype="<u2").tobytes())
    # Small native-crop previews, managed sRGB, one shared recipe per crop.
    for name in MODES:
        write_preview(directory / f"preview_{name}_{source_key}.png", transform(linear,name,scope["recipe"]), profile)
    color = (input_profile or profile).recipe()
    color["linear_to_reference"] = (np.linalg.inv(profile.matrix) @ (input_profile or profile).matrix).tolist()
    return {"file": filename, "bytes": (directory/filename).stat().st_size, "sha256": sha256_file(directory/filename), "profile": color}


def process_frame(frame: dict, args: argparse.Namespace, code_recipe: str) -> None:
    print(f"PREPARE {frame['slug']}/{frame['set_id']} {frame['cohort']}", flush=True)
    checkpoints = args.results / frame["slug"] / frame["set_id"]
    checkpoints.mkdir(parents=True, exist_ok=True)
    input_fp = fingerprint({"code":code_recipe,"sources":{k:frame[k+"_state"]["sha256"] for k in
                            ("reference","source_render","raw_render","raw_source","dng_source")},
                            "crops":[{"name":c["name"],"xywh":c["xywh"]} for c in frame["crops"]]})
    prior = {level:json.loads((checkpoints/(level+".json")).read_text(encoding="utf-8"))
             for level in args.level if (checkpoints/(level+".json")).is_file()}
    def intact(record):
        if record.get("input_fingerprint") != input_fp: return False
        for k in ("original","released"):
            saved = record["audit"][k]; path = Path(saved["path"])
            if not path.is_file() or sha256_file(path) != saved["sha256"]: return False
        return all((ROOT/p).is_file() and sha256_file(ROOT/p)==h for p,h in record["asset_hashes"].items())
    completion_path = checkpoints / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8")) if completion_path.is_file() else {}
    metadata_ready = set(args.level) != set(LEVELS) or (completion.get("input_fingerprint") == input_fp and
                    all((ROOT/p).is_file() and sha256_file(ROOT/p)==h for p,h in completion.get("metadata_hashes",{}).items()) and
                    len(completion.get("metadata_hashes",{})) == len(frame["crops"]))
    if metadata_ready and len(prior) == len(args.level) and all(intact(r) for r in prior.values()):
        print(f"REUSE FRAME {frame['set_id']}: all requested content hashes and recipes match",flush=True)
        return
    check_resources(args.scratch, 3)
    profile, scopes = prepare_scopes(frame)
    recipe = {"code": code_recipe, "reference": frame["reference_state"]["sha256"],
              "raw": frame["raw_render_state"]["sha256"], "profile": profile.sha256,
              "scopes": [{k:s[k] for k in ("name","kind","factor","input_bounds","alignment","recipe")} for s in scopes]}
    recipe_hash = fingerprint(recipe)
    for s in scopes:
        if s["kind"] == "native_crop":
            s["assets"] = {"reference": export_scope(s,"reference",s["encoded_reference"],s["reference"],profile),
                           "raw61": export_scope(s,"raw61",s["encoded_raw"],s["raw"],profile)}
    for level in args.level:
        check_resources(args.scratch, 3)
        candidate, audit = prepare_candidate(frame, level, args)
        expected = fingerprint({"recipe": recipe_hash, "candidate": audit["released"]["sha256"]})
        checkpoint = checkpoints / (level + ".json")
        old = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {}
        if old.get("fingerprint") == expected and all((ROOT/p).is_file() and sha256_file(ROOT/p)==h for p,h in old.get("asset_hashes",{}).items()):
            print(f"REUSE {frame['set_id']} {level}", flush=True)
            for s in scopes:
                if s["kind"] == "native_crop":
                    s["assets"]["jxl_"+level] = old["viewer_assets"][s["name"]]
            continue
        print(f"DECODE {frame['set_id']} {level}", flush=True)
        scratch = args.scratch / "decode"
        scratch.mkdir(parents=True, exist_ok=True)
        ppm, icc = scratch / "candidate.ppm", scratch / "candidate.icc"
        # Only these declared disposable files are replaced/removed by this run.
        ppm.unlink(missing_ok=True); icc.unlink(missing_ok=True)
        start = time.monotonic()
        first_tool_run = len(TOOL_RUNS)
        run([str(args.tools/"djxl.exe"), str(candidate), str(ppm), "--bits_per_sample=16", "--num_threads=4", f"--icc_out={icc}"], 1800)
        decoded_profile = profile_from_icc(icc.read_bytes())
        # libjxl may serialize the recognized primaries/TRC as an approximate
        # parametric profile. Use that actual decoded profile, never relabel its
        # sample values as the original ICC space. This bound checks lineage,
        # while the explicit matrix conversion below preserves the difference.
        np.testing.assert_allclose(decoded_profile.matrix, profile.matrix, atol=5e-4, rtol=0)
        grid = np.linspace(0,1,4097)
        for a,b in zip(decoded_profile.curves,profile.curves):
            np.testing.assert_allclose(decode_curve(grid,a),decode_curve(grid,b),atol=3e-5,rtol=0)
        to_reference = np.linalg.inv(profile.matrix) @ decoded_profile.matrix
        audit["decoded_profile"] = decoded_profile.recipe()
        audit["profile_conversion"] = "Decoded ICC linear RGB -> XYZ D50 -> reference ICC linear RGB"
        decoded = read_rgb_image(ppm)
        rows, assets, hashes = [], {}, {}
        try:
            if tuple(decoded.shape) != tuple(frame["shape"]) or decoded.dtype.itemsize != 2:
                raise ValueError("Decoded candidate dimensions/precision mismatch")
            for s in scopes:
                encoded = crop(decoded, ",".join(map(str,s["input_bounds"]))) if s["kind"] == "native_crop" else None
                linear = decoded_profile.linearize(encoded) if encoded is not None else reduce_linear(decoded, decoded_profile, 10)
                linear = (linear @ to_reference.T).astype(np.float32)
                measurements = measure(scope_slice(s["reference"],s["alignment"]), scope_slice(linear,s["alignment"]), profile, s["recipe"])
                for metric, raw_metric in zip(measurements,s["raw_metrics"]):
                    rows.append({"scope":s["name"], "scope_kind":s["kind"], "scale":1/s["factor"],
                                 "alignment":s["alignment"], "input_bounds":s["input_bounds"], "candidate":metric, "raw61":raw_metric})
                if s["kind"] == "native_crop":
                    asset = export_scope(s,"jxl_"+level,encoded,linear,profile,decoded_profile)
                    assets[s["name"]] = asset; s["assets"]["jxl_"+level] = asset
                    directory = Path(s["item"]["metadata"]).parent
                    for f in [directory/asset["file"], *directory.glob(f"preview_*_jxl_{level}.png")]:
                        hashes[f.relative_to(ROOT).as_posix()] = sha256_file(f)
            # Reference assets are part of each checkpoint, so deletion or manual
            # edits cannot be hidden by a valid candidate-only cache entry.
            for s in scopes:
                if s["kind"] == "native_crop":
                    directory = Path(s["item"]["metadata"]).parent
                    for key in ("reference","raw61"):
                        for f in [directory/(key+".rgb16le"),*directory.glob(f"preview_*_{key}.png")]:
                            hashes[f.relative_to(ROOT).as_posix()] = sha256_file(f)
            result = {"schema":3,"fingerprint":expected,"input_fingerprint":input_fp,"analysis_recipe":recipe,"scan_set":frame["scan_set"],
                      "set_id":frame["set_id"],"cohort":frame["cohort"],"level":level,"audit":audit,
                      "decode_seconds_and_metrics":time.monotonic()-start,"tool_runs":TOOL_RUNS[first_tool_run:],
                      "measurements":rows,"viewer_assets":assets,"asset_hashes":hashes}
            atomic_write_json(checkpoint,result)
            print(f"CHECKPOINT {frame['set_id']} {level}: {time.monotonic()-start:.1f}s", flush=True)
        finally:
            close_image(decoded); gc.collect()
            ppm.unlink(missing_ok=True); icc.unlink(missing_ok=True)
    if set(args.level) == set(LEVELS):
        metadata_hashes = {}
        for s in scopes:
            if s["kind"] != "native_crop": continue
            old = s["item"]["old_metadata"]
            old.update({"schema":3,"cohort":frame["cohort"],"analysis_recipe_sha256":recipe_hash,
                        "browser_transform_recipe":s["recipe"],"local_raw61_alignment":s["alignment"],
                        "raw61_exposure_match":{"linear_gain":1,"stops":0,"applied_to_modes":[],"method":"none"},
                        "view_modes":[{"key":k,"label":v[0],"description":v[1]} for k,v in MODES.items()],
                        "default_transform":"identity", "asset_manifest":s["assets"], "source_profile":profile.recipe()})
            old["rgb16"]["transforms"] = list(MODES)
            old["rgb16"]["sources"] = {k:v["file"] for k,v in s["assets"].items()}
            old["rgb16"]["sources"]["ps16_lossless"] = "reference.rgb16le"
            old["images_by_transform"] = {mode:{k:f"preview_{mode}_{k}.png" for k in s["assets"]} for mode in MODES}
            old["overviews_by_transform"] = old["images_by_transform"]
            old["overviews"] = old["images_by_transform"]["identity"]
            old["thumbnail"] = "preview_identity_raw61.png"
            # Publish hash-based identities; no private absolute paths or stale external transformations.
            old["build_inputs"] = {"schema":3,"recipe_sha256":recipe_hash,"reference_sha256":frame["reference_state"]["sha256"],
                                   "raw61_source_sha256":frame["raw_source_state"]["sha256"],"crop":s["input_bounds"]}
            for k in ("negpy_extreme","build_fingerprint"):
                old.pop(k,None)
            atomic_write_json(Path(s["item"]["metadata"]),old)
            path = Path(s["item"]["metadata"])
            metadata_hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
        atomic_write_json(completion_path,{"input_fingerprint":input_fp,"metadata_hashes":metadata_hashes})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Existing project checkout containing private input/outputs")
    parser.add_argument("--scratch", type=Path, required=True, help="Dedicated persistent rebuild scratch (not Windows Temp)")
    parser.add_argument("--results", type=Path, default=ROOT/"results/verified_report")
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--f45-root", type=Path, help="Optional retained f/4.5 output root containing rawtherapee_renders_f45 and rendered_ps16_jxl_matrix_f45")
    parser.add_argument("--exiftool", default=r"C:\Program Files\ExifTool\ExifTool.exe")
    parser.add_argument("--case", action="append", help="Limit to a frame ID for pilot")
    parser.add_argument("--level", action="append", choices=LEVELS)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--lossless-pilot", action="store_true")
    args = parser.parse_args(); args.level = args.level or LEVELS
    args.scratch.mkdir(parents=True, exist_ok=True); args.results.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
    inventory_path = args.results / "private_inventory.json"
    # Freeze the original viewer inventory before replacing its public metadata.
    if inventory_path.is_file():
        frames = json.loads(inventory_path.read_text())["frames"]
        if args.case: frames = [f for f in frames if f["set_id"] in args.case]
    else:
        requested = args.case; args.case = None
        all_frames = source_inventory(args)
        atomic_write_json(inventory_path,{"schema":3,"frames":all_frames})
        args.case = requested
        frames = [f for f in all_frames if not requested or f["set_id"] in requested]
    import PIL, tifffile, imagecodecs
    environment = {"code":{p:sha256_file(ROOT/p) for p in ["src/report_transforms.py","src/image_color.py",
                   "src/break_even_image_tools.py","src/color_patch_metrics.py","scripts/rebuild_verified_report.py"]},
                   "tools":{name:sha256_file(args.tools/name) for name in ("cjxl.exe","djxl.exe","jxlinfo.exe")},
                   "exiftool_sha256":sha256_file(Path(args.exiftool)),
                   "runtime":{"python":sys.version,"numpy":np.__version__,"Pillow":PIL.__version__,
                              "tifffile":tifffile.__version__,"imagecodecs":imagecodecs.__version__},
                   "policy":{"heavy_jobs":1,"codec_threads":4,"blas_threads":os.environ.get("OPENBLAS_NUM_THREADS"),
                             "priority":"below normal","memory_reserve_gib":8,"disk_reserve_gib":20}}
    code_recipe = fingerprint(environment)
    atomic_write_json(args.results/"environment.json",environment)
    for frame in frames:
        check_resources(args.scratch, 1)
        try:
            audited = verify_references(frame,args)
            if args.lossless_pilot:
                audited["lossless_pilot"] = lossless_gate(audited,args)
            atomic_write_json(args.results/frame["slug"]/frame["set_id"]/"source_audit.json",audited)
            if not args.audit_only: process_frame(audited,args,code_recipe)
        except Exception as exc:
            atomic_write_json(args.results/"last_failure.json",{"frame":frame["set_id"],"error":str(exc),"resumable":True})
            raise
    print("Requested stages completed; release validation is still required.",flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
