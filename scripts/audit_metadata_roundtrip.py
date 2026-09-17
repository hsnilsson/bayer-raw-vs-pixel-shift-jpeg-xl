"""Compare photographic metadata, or reproduce the public synthetic JXL audit.

Only field names and preservation states are exported; source metadata values
and absolute paths never enter the audit JSON. Missing fields are observations,
not an automatic archival-quality verdict.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from incremental_cache import atomic_write_json, fingerprint, sha256_file


def run(command):
    result = subprocess.run(list(map(str, command)), capture_output=True, check=True)
    return result.stdout


def snapshot(path, exiftool, tags=None):
    # ExifTool does not expose the compressed JXL codestream's ICC in this view.
    # Keep ICC out of tag diffs and test the decoder's --icc_out separately.
    tags = tags or ["EXIF:all", "XMP:all", "IPTC:all", "MakerNotes:all"]
    result = json.loads(run([exiftool, "-j", "-G1", "-s", "-struct", *["-" + t for t in tags], path]))[0]
    result.pop("SourceFile", None)
    if any(k.split(":")[-1] in ("Error", "Warning") for k in result):
        raise ValueError("ExifTool reported an error or warning; inspect the input locally")
    return result


def compare(source, candidate):
    rows = []
    for field in sorted(source.keys() | candidate.keys()):
        if field not in source:
            status = "added"
        elif field not in candidate:
            status = "missing"
        elif source[field] == candidate[field]:
            status = "preserved"
        else:
            status = "changed"
        rows.append({"field": field, "status": status})
    return {"counts": dict(Counter(row["status"] for row in rows)), "fields": rows}


def diff_files(source, candidate, exiftool):
    return {"source_sha256": sha256_file(source), "candidate_sha256": sha256_file(candidate),
            **compare(snapshot(source, exiftool), snapshot(candidate, exiftool))}


def smoke(args):
    import numpy as np
    from PIL import __version__ as pillow_version
    import tifffile
    from break_even_image_tools import read_ppm
    from image_color import profile_from_icc
    from rebuild_verified_report import TAGS

    # A fresh directory prevents overwriting any retained captures or prior run.
    args.work.mkdir(parents=True, exist_ok=False)
    source = args.work / "synthetic.tif"
    ppm = args.work / "synthetic.ppm"
    icc = args.work / "source.icc"
    pixels = ((np.arange(64 * 64 * 3, dtype=np.uint32) * 193) % 65536).astype(np.uint16).reshape(64, 64, 3)
    profile_bytes = (ROOT / "tests/fixtures/rtv4_large.icc").read_bytes()
    icc.write_bytes(profile_bytes)
    ppm.write_bytes(b"P6\n64 64\n65535\n" + pixels.astype(">u2").tobytes())
    tifffile.imwrite(source, pixels, photometric="rgb", metadata=None,
                     extratags=[(34675, "B", len(profile_bytes), profile_bytes, False)])
    # Deliberately fake fields include values outside the report's curated list.
    run([args.exiftool, "-overwrite_original", "-Make=Metadata audit fixture", "-Model=Synthetic RGB16",
         "-Orientation#=1", "-LensModel=Synthetic lens", "-FocalLength=50", "-FNumber=8",
         "-ExposureTime=1/125", "-ISO=100", "-DateTimeOriginal=2000:01:01 00:00:00",
         "-EXIF:CreateDate=2000:01:01 00:00:00", "-XMP:CreateDate=2000:01:01 00:00:00",
         "-XMP-aux:LensInfo=50 50 8 8", "-Artist=Synthetic author", "-Copyright=Synthetic example",
         "-ImageDescription=Synthetic metadata preservation fixture", "-XMP-dc:Subject=Synthetic keyword",
         "-XMP-dc:Title=Synthetic title", "-GPSLatitude=0", "-GPSLatitudeRef=N",
         "-GPSLongitude=0", "-GPSLongitudeRef=E", source])
    expected = snapshot(source, args.exiftool, TAGS)
    source_profile = profile_from_icc(profile_bytes)
    records = []
    for distance in (0, .05):
        encoded = args.work / f"d{distance:g}.jxl"
        decoded = encoded.with_suffix(".ppm")
        decoded_icc = encoded.with_suffix(".icc")
        png = encoded.with_suffix(".png")
        run([args.tools / "cjxl.exe", ppm, encoded, "--container=1", "-x", f"icc_pathname={icc}",
             "-d", str(distance), "-e", "7", "--num_threads=1"])
        before = diff_files(source, encoded, args.exiftool)
        run([args.exiftool, "-m", "-overwrite_original", "-TagsFromFile", source,
             *["-" + field for field in expected], encoded])
        selected = compare(expected, snapshot(encoded, args.exiftool, TAGS))
        if any(row["status"] != "preserved" for row in selected["fields"]):
            raise ValueError("Curated metadata did not survive the explicit copy")
        run([args.tools / "djxl.exe", encoded, decoded, "--bits_per_sample=16", "--num_threads=1",
             f"--icc_out={decoded_icc}"])
        run([args.tools / "djxl.exe", encoded, png, "--bits_per_sample=16", "--num_threads=1"])
        arr = read_ppm(decoded)
        exact = bool(np.array_equal(pixels, arr))
        arr._mmap.close()
        actual_profile = profile_from_icc(decoded_icc.read_bytes())
        equivalent = (np.allclose(source_profile.matrix, actual_profile.matrix, rtol=0, atol=2e-5)
                      and source_profile.curves == actual_profile.curves)
        icc_exact = profile_bytes == decoded_icc.read_bytes()
        if distance == 0 and not (exact and icc_exact and equivalent):
            raise ValueError("Lossless RGB16/ICC round trip failed")
        records.append({"distance": distance, "pixel_exact": exact,
                        "icc": {"source_sha256": sha256_file(icc), "decoded_sha256": sha256_file(decoded_icc),
                                "byte_exact": icc_exact, "matrix_trc_equivalent": bool(equivalent)},
                        "ppm_input_to_jxl_before_metadata_copy": before,
                        "curated_fields_after_copy": selected,
                        "tiff_to_jxl_after_copy": diff_files(source, encoded, args.exiftool),
                        "jxl_to_decoded_ppm": diff_files(encoded, decoded, args.exiftool),
                        "jxl_to_decoded_png": diff_files(encoded, png, args.exiftool)})
    code = ["scripts/audit_metadata_roundtrip.py", "scripts/rebuild_verified_report.py",
            "src/image_color.py", "tests/fixtures/rtv4_large.icc"]
    payload = {"schema": 3, "scope": "Synthetic 64x64 RGB16 TIFF, PPM input, explicit curated metadata copy; distances 0 and 0.05",
               "source": "Generated pixels and fictional metadata; no private photographic inputs",
               "limits": "Fields absent from the fixture are untested. Missing means not reported by ExifTool in the photographic-tag view, which excludes ICC. ICC is checked using djxl --icc_out. This is the report's PPM-input workflow, not every TIFF/JXL application path. Matrix/TRC comparison covers the fixture profile only.",
               "tools": {name: {"sha256": sha256_file(args.tools / (name + ".exe")),
                                "version": run([args.tools / (name + ".exe"), "--version"]).decode().splitlines()[0]}
                         for name in ("cjxl", "djxl")},
               "exiftool": {"version": run([args.exiftool, "-ver"]).decode().strip(), "sha256": sha256_file(args.exiftool)},
               "python_packages": {"numpy": np.__version__, "Pillow": pillow_version, "tifffile": tifffile.__version__},
               "recipe_code": {p: sha256_file(ROOT / p) for p in code}, "records": records}
    payload["evidence_id"] = "metadata-" + fingerprint(payload)[:16]
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    simple = sub.add_parser("diff", help="Compare any two ExifTool-readable files, without publishing metadata values")
    simple.add_argument("--source", type=Path, required=True)
    simple.add_argument("--candidate", type=Path, required=True)
    pilot = sub.add_parser("smoke", help="Generate and test a synthetic TIFF -> PPM -> JXL -> PPM/PNG round trip")
    pilot.add_argument("--tools", type=Path, required=True, help="libjxl 0.11.2 directory containing cjxl.exe/djxl.exe")
    pilot.add_argument("--work", type=Path, required=True, help="New directory under ignored results/ or work/")
    for command in (simple, pilot):
        command.add_argument("--exiftool", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new output to preserve the previous audit")
    payload = smoke(args) if args.command == "smoke" else diff_files(args.source, args.candidate, args.exiftool)
    atomic_write_json(args.output, payload)
    print(payload.get("evidence_id", json.dumps(payload.get("counts", {}))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
