"""Fail publication on mixed data, stale code, cohort/byte errors or stale assets.

Uses the standard library so the same gate can run in the Pages workflow.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from incremental_cache import fingerprint,sha256_file

LEVELS=("d003","d005","d010","d020","d022","d025","d028","d030","d100","d200")
MODES=("identity","shadow_recovery_luma_p12","highlight_separation_luma_p88_p998","negative_density_hard_print","negative_density_hard_shadow_recovery")


def require(condition,message):
    if not condition:raise ValueError(message)


def read(path):return json.loads(Path(path).read_text(encoding="utf-8"),parse_constant=lambda x:(_ for _ in ()).throw(ValueError("Nonfinite JSON: "+x)))


def public_values(value):
    if isinstance(value,dict):
        for key,item in value.items():
            require(key not in ("latitude_reference_winner","archive_value_pass"),"Withdrawn scientific verdict remains in current data")
            public_values(key)
            public_values(item)
    elif isinstance(value,list):
        for item in value:public_values(item)
    elif isinstance(value,str):
        require(not re.search(r"(?<![A-Za-z0-9+._-])[A-Za-z]:[\\/]|\\\\[^\\]+\\",value) and not value.startswith("/"),"Private absolute path leaked into public evidence")
    elif isinstance(value,float):require(math.isfinite(value),"Nonfinite metric")


def safe_path(site,relative):
    path=site/relative
    require(not Path(relative).is_absolute() and ".." not in Path(relative).parts,"Unsafe public asset path")
    require(not relative.startswith(("/","\\")) and path.resolve().is_relative_to(site.resolve()),"Public asset escaped its site directory")
    require(path.is_file(),"Missing release asset: "+relative)
    return path


def check_pixel_payload(path,asset,decoded_bytes):
    require(path.stat().st_size==asset["bytes"],"Wrong compressed payload length")
    require(sha256_file(path)==asset["sha256"],"Viewer transport hash mismatch")
    planes=gzip.decompress(path.read_bytes())
    require(len(planes)==asset["decoded_bytes"]==decoded_bytes,"Wrong decoded RGB16 payload length")
    half=len(planes)//2;raw=bytearray(len(planes))
    raw[::2]=planes[:half];raw[1::2]=planes[half:]
    require(hashlib.sha256(raw).hexdigest()==asset["decoded_sha256"],"Viewer pixel hash mismatch")


def check(site:Path,check_html=True):
    site=site.resolve();release=read(site/"data/release.json")
    require((site/"data/reproduction.md").read_bytes()==(ROOT/"REPRODUCIBILITY.md").read_bytes(),
            "Published reproduction instructions differ from the repository source")
    public_values(release)
    require(release.get("schema")==3,"A complete schema-3 release is required")
    unsigned={k:v for k,v in release.items() if k not in ("run_id","measurements_csv_sha256")}
    require(release["run_id"]=="verified-"+fingerprint(unsigned)[:16],"Release identity does not match its contents")
    require(release["analysis_identity"]==fingerprint(release["environment"]),"Mixed analysis environment")
    for group in (release["environment"]["code"],release["report_code"]):
        for relative,expected in group.items():require(sha256_file(ROOT/relative)==expected,"Code changed after release: "+relative)
    design=read(ROOT/"metadata/verified_experiment.json")
    require(release["experiment_sha256"]==sha256_file(ROOT/"metadata/verified_experiment.json"),"Experiment declaration changed after release")
    frames={(f["slug"],f["set_id"]):f for f in release["frames"]}
    require(len(frames)==len(release["frames"])==len(design["frames"]),"Frame count/identity mismatch")
    require(release["summary"]["cohort_frames"]==dict(Counter(f["cohort"] for f in frames.values())),"Cohort denominator mismatch")
    for f in design["frames"]:
        actual=frames.get((f["slug"],f["set_id"]))
        require(actual is not None and actual["cohort"]==f["cohort"] and actual["crops"]==f["crops"],"Capture/cohort/crop selection changed")
        require(actual["lossless_pilot"]["pixel_exact"] and actual["lossless_pilot"]["metadata_exact"] and actual["lossless_pilot"]["icc_equivalent"],"Lossless gate failed")
        require(actual["littlecms_max_display_code_error"]<=2,"ICC oracle gate failed")
    candidate_rows={};expected_csv=[];raw_fingerprints={}
    for key,recipe in release["analysis_recipes"].items():require(fingerprint(recipe)==key,"Altered analysis recipe")
    for row in release["candidates"]:
        key=(row["slug"],row["set_id"],row["level"])
        require(key not in candidate_rows,"Duplicate candidate row")
        candidate_rows[key]=row
        f=frames[key[:2]]
        recipe=release["analysis_recipes"][row["recipe_sha256"]]
        require(recipe["code"]==release["analysis_identity"] and recipe["reference"]==f["reference"]["sha256"] and
                recipe["raw"]==f["raw_render"]["sha256"] and recipe["profile"]==f["profile"]["icc_sha256"],"Wrong recipe source")
        require(row["level"] in LEVELS and row["cohort"]==f["cohort"],"Candidate cohort or distance mismatch")
        require(row["decision_level"]==(row["level"] not in ("d100","d200")),"Stress control entered decision denominator")
        require(row["raw61_bytes"]==f["raw61"]["bytes"],"Wrong paired RAW byte denominator")
        require(row["encoded_bytes"]==sum(row["retained_components"].values()),"Retained size omits required components")
        primary=f["cohort"]=="primary_compressed_independent"
        require(row["within_primary_raw61_budget"]==(primary and row["encoded_bytes"]<=row["raw61_bytes"]),"Wrong strict size threshold")
        require(abs(row["size_vs_raw61_pct"]-100*row["encoded_bytes"]/row["raw61_bytes"])<1e-10,"Incorrect byte label")
        require(row["metadata_pass"] is True,"Missing metadata validation")
        scopes={(m["scope"],m["candidate"]["transform"]) for m in row["measurements"]}
        expected={(name,mode) for name in ["full_frame_box10",*[c["name"] for c in f["crops"]]] for mode in MODES}
        require(scopes==expected and len(scopes)==len(row["measurements"]),"Lost, duplicate or unknown measurement scope")
        native=[]
        for m in row["measurements"]:
            reduced=m["scope"]=="full_frame_box10"
            require(m["scope_kind"]==("reduced_full_frame" if reduced else "native_crop") and m["scale"]==(.1 if reduced else 1),"Wrong measurement scale")
            require(m["candidate"]["transform"]==m["raw61"]["transform"],"Mismatched baseline transform")
            if not reduced:
                require(m["input_bounds"]==next(c["xywh"] for c in f["crops"] if c["name"]==m["scope"]),"Wrong crop identity")
                native.append(m)
            raw_key=(*key[:2],m["scope"],m["raw61"]["transform"])
            baseline=fingerprint({"alignment":m["alignment"],"raw61":m["raw61"]})
            require(raw_key not in raw_fingerprints or raw_fingerprints[raw_key]==baseline,"RAW baseline changed across compression distances")
            raw_fingerprints[raw_key]=baseline
            flat={k:row[k] for k in ("scan_set","set_id","cohort","level","encoded_bytes","encoded_sha256","raw61_bytes","size_vs_raw61_pct")}
            flat.update({"scope":m["scope"],"scope_kind":m["scope_kind"],"scale":m["scale"],"transform":m["candidate"]["transform"],
                         "valid_fraction":m["alignment"]["valid_fraction"],"alignment_applied":m["alignment"]["applied"]})
            for role in ("candidate","raw61"):flat.update({role+"_"+k:v for k,v in m[role].items() if k!="transform"})
            flat["run_id"]=release["run_id"];expected_csv.append({k:"" if v is None else str(v) for k,v in flat.items()})
        require(row["alignment_review_pass"]==all(m["alignment"]["applied"] and m["alignment"]["valid_fraction"]>=.8 for m in native),"Incorrect registration screen")
        color=[m for m in native if m["candidate"]["transform"] in ("identity","negative_density_hard_print")]
        require(row["native_color_closer_than_raw61"]==all(m["candidate"]["delta_e00_p95"]<=m["raw61"]["delta_e00_p95"] for m in color),"Incorrect native color screen")
        hp=[m for m in native if m["candidate"]["transform"]=="identity"]
        require(row["native_structure_closer_than_raw61"]==all(m["candidate"]["highpass_reference_rms"]>2**-23 and m["candidate"]["structure_loss"] is not None and m["raw61"]["structure_loss"] is not None and m["candidate"]["structure_loss"]<=m["raw61"]["structure_loss"] for m in hp),"Incorrect native structure screen")
    require(set(candidate_rows)=={(*key,level) for key in frames for level in LEVELS},"Incomplete frame-distance matrix")
    primary=[r for r in candidate_rows.values() if r["cohort"]=="primary_compressed_independent"]
    decisions=[r for r in primary if r["decision_level"]]
    summary=release["summary"]
    for name,value in {"frames":len(frames),"candidates":len(candidate_rows),"primary_frames":len(primary)//len(LEVELS),"primary_candidate_rows":len(primary),
                       "primary_decision_rows":len(decisions),"primary_decision_within_budget":sum(r["within_primary_raw61_budget"] for r in decisions),
                       "native_crops":sum(len(f["crops"]) for f in frames.values())}.items():require(summary[name]==value,"Incorrect summary: "+name)
    viewer_keys=set()
    for relative,expected in release["asset_hashes"].items():
        path=safe_path(site,relative);require(sha256_file(path)==expected,"Changed release asset: "+relative)
        if path.name=="metadata.json":
            meta=read(path);public_values(meta)
            matching=[f for f in frames.values() if f["scan_set"]==meta["scan_set"] and f["set_id"]==meta["set_id"]]
            require(len(matching)==1,"Viewer capture identity mismatch");f=matching[0]
            viewer_key=(f["slug"],f["set_id"],meta["crop_name"])
            require(viewer_key not in viewer_keys,"Duplicate viewer crop");viewer_keys.add(viewer_key)
            crop=next((c for c in f["crops"] if c["name"]==meta["crop_name"]),None)
            require(crop is not None and meta["crop"]==crop["xywh"],"Wrong viewer crop coordinates")
            rgb=meta["rgb16"]
            require([rgb["width"],rgb["height"]]==crop["xywh"][2:],"Wrong viewer crop dimensions")
            require(meta["schema"]==3 and rgb["bytes_per_sample"]==2 and rgb["channels"]==3 and rgb["endianness"]=="little","Wrong viewer precision")
            require(rgb.get("transport")=="gzip-byteplanes-v1","Wrong viewer transport")
            require(meta["source_profile"]==f["profile"],"Wrong viewer reference ICC")
            recipe=release["analysis_recipes"][meta["analysis_recipe_sha256"]]
            scope=next(s for s in recipe["scopes"] if s["name"]==meta["crop_name"])
            require(meta["browser_transform_recipe"]==scope["recipe"] and meta["local_raw61_alignment"]==scope["alignment"],"Viewer transform/registration differs from measurements")
            require(meta["build_inputs"]["reference_sha256"]==f["reference"]["sha256"] and meta["build_inputs"]["raw61_source_sha256"]==f["raw61"]["sha256"],"Wrong viewer source")
            require([m["key"] for m in meta["view_modes"]]==list(MODES),"Undeclared viewer transform")
            require(set(meta["asset_manifest"])=={"reference","raw61",*("jxl_"+level for level in LEVELS)},"Incomplete viewer quality matrix")
            for key,asset in meta["asset_manifest"].items():
                p=safe_path(site,(path.parent/asset["file"]).relative_to(site).as_posix())
                require(release["asset_hashes"].get(p.relative_to(site).as_posix())==asset["sha256"],"Unbound viewer payload")
                check_pixel_payload(p,asset,rgb["width"]*rgb["height"]*6)
                require(rgb["sources"][key]==asset["file"],"Viewer source mapping mismatch")
                if key.startswith("jxl_"):
                    row=candidate_rows[(f["slug"],f["set_id"],key[4:])]
                    require(asset["profile"]["icc_sha256"]==row["decoded_profile"]["icc_sha256"],"Wrong actual decoded ICC")
                    require(all(asset["profile"].get(k)==v for k,v in row["decoded_profile"].items()),"Viewer ICC recipe differs from decoded profile")
                    require(asset["decoded_sha256"]==row["viewer_pixels"][meta["crop_name"]],"Viewer differs from measured candidate pixels")
                    require(meta["analysis_recipe_sha256"]==row["recipe_sha256"],"Mixed viewer and measurement recipes")
                else:
                    require(asset["decoded_sha256"]==f["viewer_references"][meta["crop_name"]][key],"Viewer baseline differs from measured reference")
                    require(all(asset["profile"].get(k)==v for k,v in f["profile"].items()),"Wrong baseline profile")
                source_matrix=asset["profile"]["rgb_to_xyz_d50"];target_matrix=f["profile"]["rgb_to_xyz_d50"]
                transform=asset["profile"]["linear_to_reference"]
                require(all(abs(sum(target_matrix[i][k]*transform[k][j] for k in range(3))-source_matrix[i][j])<1e-10 for i in range(3) for j in range(3)),"Wrong ICC conversion matrix")
    require(viewer_keys=={(f["slug"],f["set_id"],c["name"]) for f in frames.values() for c in f["crops"]},"Missing viewer crops")
    csv_path=site/"data/measurements.csv"
    require(sha256_file(csv_path)==release["measurements_csv_sha256"],"CSV hash mismatch")
    with csv_path.open(encoding="utf-8",newline="") as f:actual_csv=list(csv.DictReader(f))
    require(actual_csv==expected_csv,"CSV and JSON measurements differ")
    for name,item in release["evidence"].items():
        for relative,expected in item["recipe_code"].items():require(sha256_file(ROOT/relative)==expected,"Changed auxiliary source: "+relative)
        p=safe_path(site,item["file"]);require(sha256_file(p)==item["sha256"],"Auxiliary evidence hash mismatch")
        data=read(p);public_values(data)
        require(data["evidence_id"]==item["evidence_id"] and data["schema"]==3,"Mixed auxiliary release")
        for relative,expected in data.get("recipe_code",{}).items():require(sha256_file(ROOT/relative)==expected,"Changed auxiliary code: "+relative)
        if name=="dng":
            require(data["provenance"]["djxl_sha256"]==release["environment"]["tools"]["djxl.exe"],"DNG decoder differs from pinned tool")
            for route in data["routes"]:
                rows=route["records"];s=route["summary"]
                require(s["files"]==len(rows)==16,"Incorrect DNG denominator")
                require(s["cohort_frames"]==dict(Counter(r["cohort"] for r in rows)),"Incorrect DNG cohorts")
                for r in rows:require(r["within_200_mib"]==(r["candidate_bytes"]<=200*2**20),"Wrong DNG budget")
                require(s["within_200_mib"]==sum(r["within_200_mib"] for r in rows),"Incorrect DNG budget count")
                require(s["technical_passed"]==sum(r["technical_pass"] for r in rows),"Incorrect DNG technical count")
                if route["level"]=="lossless":require(all(c["pixel_exact"] for r in rows for c in r["camera_sample_metrics"]),"Lossless camera sample mismatch")
        if name=="public":
            for tool,expected in data["tools"].items():require(expected==release["environment"]["tools"][tool+".exe"],"Public codec differs from pinned tool")
            require(len(data["records"])==6,"Public suite incomplete")
            for case in data["records"]:
                require([r["distance"] for r in case["levels"]]==[0,.03,.05,.10],"Public distance matrix incomplete")
                require(case["levels"][0]["pixel_exact"] and case["levels"][0]["decoded_profile"]["icc_sha256"]==case["working_profile"]["icc_sha256"],"Public lossless gate failed")
        if name=="combiner":
            require(len(data["cases"])==2 and sum(len(c["crops"]) for c in data["cases"])==5,"Combiner scope changed")
            plan=read(ROOT/"metadata/combiner_crop_plan.json")
            require({(c["sequence"],s["name"],tuple(s["crop_xywh"])) for c in data["cases"] for s in c["crops"]}==
                    {(c["sequence"],s["name"],tuple(s["crop"])) for c in plan["cases"] for s in c["crops"]},"Combiner crop identities changed")
        if name=="controlled":require(len(data["cases"])==4 and len(data["source_states"])==16,"Controlled source denominator changed")
        if name in ("contexts","lineage"):
            records=data["records"] if name=="contexts" else data["frames"]
            require({(r["scan_set"],r["set_id"]) for r in records}=={(f["scan_set"],f["set_id"]) for f in frames.values()} and len(records)==len(frames),"Auxiliary capture coverage changed")
            for record in records:
                f=next(f for f in frames.values() if f["scan_set"]==record["scan_set"] and f["set_id"]==record["set_id"])
                if name=="contexts":
                    require(record["source_sha256"]==f["reference"]["sha256"] and record["icc_sha256"]==f["profile"]["icc_sha256"] and record["crops"]==f["crops"],"Context source/crop mismatch")
                else:
                    require({e["level"] for e in record["encodes"]}==set(LEVELS),"Incomplete image codestream audit")
                    for encoded in record["encodes"]:
                        row=candidate_rows[(f["slug"],f["set_id"],encoded["level"])]
                        require(encoded["released_file_sha256"]==row["encoded_sha256"] and encoded["original_file_sha256"]==row["original_encoded_sha256"] and encoded["metadata_only_repair"],"Metadata repair lineage mismatch")
                    require({c["crop"] for c in record["raw_viewer_quantization"]}=={c["name"] for c in f["crops"]},"Incomplete RAW viewer audit")
                    for crop in record["raw_viewer_quantization"]:
                        require(crop["source_resampling_support_inside_bounds"],"Invalid RAW resampling support")
                        require({r["level"] for r in crop["native_highpass_boundary_sensitivity"]}==set(LEVELS),"Incomplete boundary audit")
    if check_html:
        build=read(site/"data/site-build.json")
        require(build["release_sha256"]==sha256_file(site/"data/release.json") and build["html_sha256"]==sha256_file(site/"index.html"),"HTML belongs to another release")
        expected_redirects={str(Path(p).with_name("index.html")).replace("\\","/") for p in release["asset_hashes"] if p.endswith("/metadata.json")}
        require(set(build["redirects"])==expected_redirects,"Missing standalone viewer redirects")
        for relative,expected in build["redirects"].items():
            path=safe_path(site,relative)
            require(sha256_file(path)==expected,"Stale standalone viewer")
            link=re.search(r'href="([^"]+)"',path.read_text(encoding="utf-8"))
            require(link is not None,"Standalone viewer has no report link")
            target=urlsplit(html.unescape(link.group(1)))
            metadata=read(path.with_name("metadata.json"))
            require(not target.scheme and not target.netloc and target.fragment=="visual" and
                    (path.parent/unquote(target.path)).resolve()==(site/"index.html").resolve(),"Standalone viewer targets another report")
            require(parse_qs(target.query)=={"scan":[metadata["scan_set"]],"frame":[metadata["set_id"]],"crop":[metadata["crop_name"]]},
                    "Standalone viewer selects another capture or crop")
        text=(site/"index.html").read_text(encoding="utf-8")
        require(release["run_id"] in text,"HTML release label mismatch")
        match=re.search(r'<script type="application/json" id="cropViewerData">(.*?)</script>',text,re.S)
        require(match is not None,"Missing crop viewer manifest")
        viewers=json.loads(match.group(1));require(len(viewers)==summary["native_crops"],"HTML viewer denominator mismatch")
        for viewer in viewers:
            for c in viewer["candidates"]:
                if c["key"].startswith("jxl_"):
                    matching=[r for r in candidate_rows.values() if r["scan_set"]==viewer["scanSet"] and r["set_id"]==viewer["setId"] and r["level"]==c["key"][4:]]
                    require(bool(matching) and abs(c["storageMib"]-matching[0]["encoded_bytes"]/2**20)<1e-10,"Viewer/table size mismatch")
    return {"run_id":release["run_id"],"frames":len(frames),"candidates":len(candidate_rows),"measurement_rows":len(expected_csv),"assets":len(release["asset_hashes"])}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site",type=Path,default=ROOT/"site")
    p.add_argument("--data-only",action="store_true")
    args=p.parse_args()
    print(json.dumps(check(args.site,not args.data_only),indent=2));return 0


if __name__=="__main__":raise SystemExit(main())
