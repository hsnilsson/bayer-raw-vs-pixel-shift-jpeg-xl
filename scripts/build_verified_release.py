"""Assemble a public, path-free release from complete audited checkpoints."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
import statistics
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts")]
from incremental_cache import fingerprint, sha256_file, atomic_write_json
from rebuild_verified_report import LEVELS, atomic_bytes
from native_registration import validate_recipe

REPORT_CODE = ("scripts/build_verified_release.py", "scripts/render_verified_report.py",
               "scripts/generate_break_even_report_site.py", "scripts/finalize_verified_viewers.py",
               "scripts/check_verified_release.py", "scripts/run_responsive.py", "scripts/run_verified_rebuild.py",
               "src/preview_cache.py", "src/viewer_overviews.py", "src/report_color.js", "src/report_styles.css",
               "src/report_metadata.py")
REPORT_DOCUMENTS = {"REPRODUCIBILITY.md": "data/reproduction.md",
                    "docs/metadata-icc-audit.md": "data/metadata-icc-audit.md"}


def copy_documents(site, assets):
    for source, destination in REPORT_DOCUMENTS.items():
        atomic_bytes(site/destination, (ROOT/source).read_bytes())
    for relative in (*REPORT_DOCUMENTS.values(), "data/review-notes.md"):
        assets[relative] = sha256_file(site/relative)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def public_state(value):
    return {k:value[k] for k in ("bytes","sha256")}


def candidate_screen(record):
    native = [m for m in record["measurements"] if m["scope_kind"] == "native_crop"]
    color = [m for m in native if m["candidate"]["transform"] in ("identity","negative_density_hard_print")]
    structure = [m for m in native if m["candidate"]["transform"] == "identity"]
    aligned = bool(native) and all(m["alignment"]["applied"] and m["alignment"]["valid_fraction"] >= .8 for m in native)
    color_ok = bool(color) and all(m["candidate"]["delta_e00_p95"] <= m["raw61"]["delta_e00_p95"] for m in color)
    structure_ok = bool(structure) and all(m["candidate"]["highpass_reference_rms"] > 2**-23 and
                       m["candidate"]["structure_loss"] is not None and m["raw61"]["structure_loss"] is not None and
                       m["candidate"]["structure_loss"] <= m["raw61"]["structure_loss"] for m in structure)
    return {"alignment_review_pass":aligned,"native_color_closer_than_raw61":color_ok,
            "native_structure_closer_than_raw61":structure_ok}


def build(results: Path, site: Path, verify_private: bool) -> dict:
    inventory = read(results/"private_inventory.json")["frames"]
    environment = read(results/"environment.json")
    code = fingerprint(environment)
    for path, expected in environment["code"].items():
        if sha256_file(ROOT/path) != expected:
            raise ValueError(f"Analysis code changed after the run: {path}")
    frames, candidates, metrics, assets, recipes = [], [], [], {}, {}
    elapsed=[];decoder_peaks=[];refinement_elapsed=[]
    seen = set()
    for item in inventory:
        directory = results/item["slug"]/item["set_id"]
        audit = read(directory/"source_audit.json")
        complete = read(directory/"complete.json")
        if complete.get("metadata_export",{}).get("script_sha256")!=sha256_file(ROOT/"scripts/finalize_verified_viewers.py"):
            raise ValueError("Run finalize_verified_viewers.py after completing the pixel rebuild")
        if not audit.get("reference_pixel_identity") or not audit.get("lossless_pilot",{}).get("pixel_exact"):
            raise ValueError("Source audit or real-image lossless gate is missing")
        if verify_private:
            for key in ("reference","source_render","raw_render","raw_source","dng_source"):
                saved = audit[key+"_state"]
                if sha256_file(Path(saved["path"])) != saved["sha256"]:
                    raise ValueError(f"Source changed after audit: {item['set_id']} {key}")
        viewer_metadata={};decoded_hashes=set()
        for path, expected in complete["metadata_hashes"].items():
            if sha256_file(ROOT/path) != expected:
                raise ValueError(f"Viewer metadata changed after completion: {path}")
            assets[str((ROOT/path).relative_to(site).as_posix())] = expected
            metadata=read(ROOT/path)
            viewer_metadata[metadata["crop_name"]]=metadata
            if metadata["rgb16"].get("transport")!="gzip-byteplanes-v1":raise ValueError("Viewer transport has not been finalized")
            for asset in metadata["asset_manifest"].values():
                payload=(ROOT/path).parent/asset["file"]
                if sha256_file(payload)!=asset["sha256"]:raise ValueError("Packed viewer bytes changed")
                assets[payload.relative_to(site).as_posix()]=asset["sha256"]
                decoded_hashes.add(asset["decoded_sha256"])
        raw = audit["raw_source_state"]
        frames.append({"scan_set":audit["scan_set"],"slug":item["slug"],"set_id":item["set_id"],"cohort":audit["cohort"],
                       "shape":audit["shape"],"raw61":public_state(raw),"source_dng":public_state(audit["dng_source_state"]),
                       "source_render":public_state(audit["source_render_state"]),"raw_render":public_state(audit["raw_render_state"]),
                       "reference":public_state(audit["reference_state"]),"profile":audit["profile"],
                       "viewer_references":{name:{role:meta["asset_manifest"][role]["decoded_sha256"] for role in ("reference","raw61")}
                                            for name,meta in viewer_metadata.items()},
                       "capture_type":{k.split(":")[-1]:v for k,v in audit["capture_metadata"].items()
                                       if k.split(":")[-1] in ("SonyRawFileType","Compression","PixelShiftInfo")},
                       "crops":[{"name":c["name"],"xywh":c["xywh"]} for c in item["crops"]],
                       "lossless_pilot":audit["lossless_pilot"],"littlecms_max_display_code_error":audit["littlecms_max_display_code_error"]})
        for level in LEVELS:
            record = read(directory/(level+".json"))
            validate_recipe(ROOT, item, record["analysis_recipe"])
            elapsed.append(record["decode_seconds_and_metrics"])
            refinement_elapsed.append(record.get("native_registration_seconds",0))
            decoder_peaks.extend(t["sampled_peak_working_bytes"] for t in record["tool_runs"] if t["tool"].lower()=="djxl.exe")
            key = (item["slug"],item["set_id"],level)
            if key in seen: raise ValueError(f"Duplicate candidate {key}")
            seen.add(key)
            if record["analysis_recipe"]["code"] != code or record["input_fingerprint"] != complete["input_fingerprint"]:
                raise ValueError(f"Mixed analysis identities: {key}")
            if record["analysis_recipe"]["reference"] != audit["reference_state"]["sha256"]:
                raise ValueError(f"Mixed reference: {key}")
            if record["cohort"] != audit["cohort"] or not record["audit"]["metadata_pass"]:
                raise ValueError(f"Incomplete candidate audit: {key}")
            if verify_private:
                for role in ("original","released"):
                    saved = record["audit"][role]
                    if sha256_file(Path(saved["path"])) != saved["sha256"]:
                        raise ValueError(f"Encoded file changed: {key} {role}")
            for path, expected in record["asset_hashes"].items():
                payload=ROOT/path
                if sha256_file(payload) != expected: raise ValueError(f"Viewer pixel/preview mismatch: {path}")
                if payload.resolve().is_relative_to((results/"viewer-pixels").resolve()):
                    if expected not in decoded_hashes:raise ValueError("Unbound retained pixel cache")
                    continue
                relative=payload.relative_to(site).as_posix()
                if relative in assets and assets[relative] != expected:
                    raise ValueError(f"Mixed viewer asset: {path}")
                assets[relative] = expected
            for crop,asset in record["viewer_assets"].items():
                if asset["sha256"]!=viewer_metadata[crop]["asset_manifest"]["jxl_"+level]["decoded_sha256"]:
                    raise ValueError("Viewer pixels do not match the measured decode")
            scopes = {(m["scope"],m["candidate"]["transform"]) for m in record["measurements"]}
            if len(scopes) != (len(item["crops"])+1)*5 or len(record["measurements"]) != len(scopes):
                raise ValueError(f"Missing/duplicate measurement scopes: {key}")
            encoded = record["audit"]["released"]
            recipe_sha=fingerprint(record["analysis_recipe"])
            recipes[recipe_sha]=record["analysis_recipe"]
            paired = audit["cohort"] == "primary_compressed_independent"
            row = {"scan_set":audit["scan_set"],"slug":item["slug"],"set_id":item["set_id"],"level":level,
                   "cohort":audit["cohort"],"decision_level":level not in ("d100","d200"),
                   "encoded_bytes":encoded["bytes"],"encoded_sha256":encoded["sha256"],
                   "original_encoded_sha256":record["audit"]["original"]["sha256"],
                   "raw61_bytes":raw["bytes"],"size_vs_raw61_pct":100*encoded["bytes"]/raw["bytes"],
                   "within_primary_raw61_budget":paired and encoded["bytes"] <= raw["bytes"],
                   "metadata_pass":True,"metadata_repaired_fields":record["audit"]["repaired_fields"],
                   "retained_components":{"jxl_file":encoded["bytes"],"required_external_sidecars":0},
                   "decoded_profile":record["audit"]["decoded_profile"],"recipe_sha256":recipe_sha,
                   "viewer_pixels":{name:asset["sha256"] for name,asset in record["viewer_assets"].items()},
                   "measurements":record["measurements"],**candidate_screen(record)}
            candidates.append(row)
            for m in record["measurements"]:
                flat = {k:row[k] for k in ("scan_set","set_id","cohort","level","encoded_bytes","encoded_sha256","raw61_bytes","size_vs_raw61_pct")}
                flat.update({"scope":m["scope"],"scope_kind":m["scope_kind"],"scale":m["scale"],"transform":m["candidate"]["transform"],
                             "valid_fraction":m["alignment"]["valid_fraction"],"alignment_applied":m["alignment"]["applied"]})
                for role in ("candidate","raw61"):
                    flat.update({role+"_"+k:v for k,v in m[role].items() if k != "transform"})
                metrics.append(flat)
    primary = [r for r in candidates if r["cohort"] == "primary_compressed_independent"]
    decision = [r for r in primary if r["decision_level"]]
    release = {"schema":3,"status":"validated", "analysis_identity":code,"environment":environment,
               "source":{"repository":"https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl",
                         "ref":"report-2026-09-17-adox-alignment"},
               "method":{"budget":"Final encoded file bytes <= paired independent compressed RAW61 bytes; photographic metadata is included",
                         "native":"Approved original-coordinate crops, linear-light RAW resampling and local registration; common valid support excludes fill and two filter-border pixels",
                         "native_registration":"The four Adox f/4.5 crops refine the coarse RAW61 shift on a 0.025-pixel grid below the upscaled RAW Nyquist frequency, then resample the original RAW render once. Their separately hash-bound recipe records code, selection, parameters and residual checks. All distances and modes are remeasured on the resulting common valid support; PS16 and JXL samples are unchanged",
                         "reduced":"Nonoverlapping 10x10 linear-light box means summarize broader image structure; incomplete bottom/right blocks omitted. Native crops provide the grain and fine-detail measurements",
                         "color":"Embedded ICC TRCs, XYZ D50 conversion, linear working RGB means over 64x64 patches, CIEDE2000 in Lab D50",
                         "structure":"Linear ICC Y minus float64 5x5 box blur with reflect padding at the cropped measurement boundary; mismatch RMS / reference high-pass RMS. Favorable structure screens require reference HP RMS > 2^-23 (float32 precision guard); native boundary sensitivity is audited separately",
                         "interpretation":"The retained PS16 render is the common reference. RAW61-vs-PS16 measures the combined effects of capture, demosaic, color, scaling, alignment and noise in this workflow",
                         "fitting":"A shared reference-derived recipe applies the same tone, color and exposure treatment to each rendered-JXL comparison",
                         "provenance":"Retained neutral source renders adopted; legacy PPMs checked pixel-for-pixel against retained TIFFs; original capture identities frozen by content hash"},
               "summary":{"cohort_frames":dict(Counter(f["cohort"] for f in frames)),"frames":len(frames),"candidates":len(candidates),
                          "primary_frames":len({r["set_id"] for r in primary}),"primary_candidate_rows":len(primary),
                          "primary_decision_rows":len(decision),"primary_decision_within_budget":sum(r["within_primary_raw61_budget"] for r in decision),
                          "native_crops":sum(len(f["crops"]) for f in frames)},
               "frames":frames,"candidates":candidates,"asset_hashes":assets,"analysis_recipes":recipes,
               "execution":{"candidate_stages":len(elapsed),"decode_measure_export_seconds_sum":sum(elapsed),
                            "native_registration_seconds_sum":sum(refinement_elapsed),
                            "decode_measure_export_seconds_median":statistics.median(elapsed),"decode_measure_export_seconds_max":max(elapsed),
                            "maximum_sampled_decoder_working_bytes":max(decoder_peaks),
                            "timing_scope":"Per-candidate decode, measurements and crop exports; excludes reference preparation, source/metadata audits and auxiliary experiments. Native registration refinements are recorded separately. Cached stages retain their original timing; this is not total rebuild wall time",
                            "observations":read(results/"execution-notes.json") if (results/"execution-notes.json").is_file() else {}}}
    evidence={}
    for key,filename in (("dng","dng-evidence.json"),("public","public-evidence.json"),("combiner","combiner-evidence.json"),
                         ("controlled","controlled-evidence.json"),("contexts","context-evidence.json"),("lineage","lineage-evidence.json"),
                         ("overviews","overview-evidence.json"),("metadata","metadata-evidence.json")):
        path=site/"data"/filename
        attachment=read(path)
        if attachment.get("schema")!=3:raise ValueError(f"Unverified auxiliary evidence: {key}")
        for relative,expected in attachment.get("asset_hashes",{}).items():
            if sha256_file(site/relative)!=expected:raise ValueError(f"Changed auxiliary asset: {relative}")
            assets[relative]=expected
        attachment_code=dict(attachment.get("recipe_code",{}))
        if key=="dng":attachment_code.update({"scripts/audit_dng_evidence.py":attachment["provenance"]["script_sha256"],
                                               "scripts/run_dng_jxl_verification.py":attachment["provenance"]["dng_reader_sha256"]})
        if key=="contexts":attachment_code["scripts/build_verified_contexts.py"]=attachment["script_sha256"]
        if key=="controlled":attachment_code["metadata/controlled_exposure_latitude_plan.json"]=attachment["plan_sha256"]
        if key=="lineage":attachment_code["profiles/rawtherapee/neutral-render.pp3"]=attachment["preset_sha256"]
        for relative,expected in attachment_code.items():
            if sha256_file(ROOT/relative)!=expected:raise ValueError(f"Changed auxiliary analysis code: {relative}")
        evidence[key]={"file":"data/"+filename,"sha256":sha256_file(path),"evidence_id":attachment["evidence_id"],"recipe_code":attachment_code}
    release["evidence"]=evidence
    copy_documents(site, assets)
    release["experiment_sha256"]=sha256_file(ROOT/"metadata/verified_experiment.json")
    release["report_code"]={p:sha256_file(ROOT/p) for p in REPORT_CODE}
    release["collection_sizes"]=[{"level":level,"primary_frames":len(primary)//len(LEVELS),
                                  "raw61_total_bytes":sum(f["raw61"]["bytes"] for f in frames if f["cohort"]=="primary_compressed_independent"),
                                  "jxl_total_bytes":sum(r["encoded_bytes"] for r in primary if r["level"]==level)} for level in LEVELS]
    release["run_id"] = "verified-" + fingerprint(release)[:16]
    for row in metrics: row["run_id"] = release["run_id"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer,fieldnames=list(metrics[0]));writer.writeheader();writer.writerows(metrics)
    atomic_bytes(site/"data/measurements.csv",buffer.getvalue().encode("utf-8"))
    release["measurements_csv_sha256"] = sha256_file(site/"data/measurements.csv")
    atomic_write_json(site/"data/release.json",release)
    return release


def refresh_public(site, source_ref):
    """Update report packaging while retaining hash-verified measurements/assets.

    This path needs only the public release. Scientific code, existing evidence
    and all image/pixel assets must remain unchanged; no private audit is rerun.
    """
    release = read(site/"data/release.json")
    unsigned = {k:v for k,v in release.items() if k not in ("run_id", "measurements_csv_sha256")}
    if release["run_id"] != "verified-" + fingerprint(unsigned)[:16]:
        raise ValueError("Existing release identity is invalid")
    for relative, expected in release["environment"]["code"].items():
        if sha256_file(ROOT/relative) != expected:
            raise ValueError("Scientific code changed; a report-only refresh is insufficient: " + relative)
    for item in release["evidence"].values():
        if sha256_file(site/item["file"]) != item["sha256"]:
            raise ValueError("Existing scientific evidence changed: " + item["file"])
        for relative, expected in item["recipe_code"].items():
            if sha256_file(ROOT/relative) != expected:
                raise ValueError("Existing evidence code changed: " + relative)
    documents = {*REPORT_DOCUMENTS.values(), "data/review-notes.md"}
    for relative, expected in release["asset_hashes"].items():
        if relative not in documents and sha256_file(site/relative) != expected:
            raise ValueError("Existing image/pixel asset changed: " + relative)
    csv_path = site/"data/measurements.csv"
    if sha256_file(csv_path) != release["measurements_csv_sha256"]:
        raise ValueError("Existing measurements CSV changed")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    attachment = read(site/"data/metadata-evidence.json")
    if attachment["schema"] != 3:
        raise ValueError("A verified metadata audit is required")
    for relative, expected in attachment["recipe_code"].items():
        if sha256_file(ROOT/relative) != expected:
            raise ValueError("Metadata audit code changed: " + relative)
    release["evidence"]["metadata"] = {"file": "data/metadata-evidence.json",
        "sha256": sha256_file(site/"data/metadata-evidence.json"), "evidence_id": attachment["evidence_id"],
        "recipe_code": attachment["recipe_code"]}
    copy_documents(site, release["asset_hashes"])
    release["source"]["ref"] = source_ref
    release["report_code"] = {p:sha256_file(ROOT/p) for p in REPORT_CODE}
    release.pop("run_id"); release.pop("measurements_csv_sha256")
    release["run_id"] = "verified-" + fingerprint(release)[:16]
    for row in rows:
        row["run_id"] = release["run_id"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    atomic_bytes(csv_path, buffer.getvalue().encode("utf-8"))
    release["measurements_csv_sha256"] = sha256_file(csv_path)
    atomic_write_json(site/"data/release.json", release)
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    parser.add_argument("--site",type=Path,default=ROOT/"site")
    parser.add_argument("--verify-private",action="store_true",help="Rehash retained full sources and candidates before assembling the release")
    parser.add_argument("--refresh-public",action="store_true",help="Refresh report packaging using unchanged public evidence; no private inputs")
    parser.add_argument("--source-ref",help="Exact source tag for a report-only refresh")
    args=parser.parse_args()
    if args.refresh_public and (args.verify_private or not args.source_ref):
        parser.error("--refresh-public requires --source-ref and cannot be combined with --verify-private")
    release=refresh_public(args.site,args.source_ref) if args.refresh_public else build(args.results,args.site,args.verify_private)
    print(release["run_id"],release["summary"])
    return 0


if __name__ == "__main__": raise SystemExit(main())
