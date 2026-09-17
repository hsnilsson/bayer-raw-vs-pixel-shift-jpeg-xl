"""Revalidate retained DNG evidence without assigning camera RGB a display ICC.

Only intersecting tiles are decoded for fresh camera-sample error measurements.
Full-segment and Adobe acceptance evidence is reused only for unchanged hashes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
import tifffile
from break_even_image_tools import read_ppm
from incremental_cache import sha256_file, atomic_write_json, fingerprint
import run_dng_jxl_verification as dng


def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_source(value, archive):
    path = Path(value)
    if path.is_file(): return path
    if "adox_vlad_resolution_target" in path.parts:
        moved = archive/"input/_superseded/adox_vlad_resolution_target_f8"/path.name
        if moved.is_file(): return moved
    raise FileNotFoundError(path)


def extract(path, windows, djxl, scratch):
    output = {w.name:np.zeros((w.height,w.width,3),dtype=np.uint16) for w in windows}
    filled = {w.name:0 for w in windows}
    with tifffile.TiffFile(path) as tif, Path(path).open("rb") as handle:
        main = dng.find_main_image(tif); page = main.page
        if not page.is_tiled or page.planarconfig != 1:
            raise ValueError("This bounded audit requires contiguous tiled RGB DNG")
        tw,th = page.tilewidth,page.tilelength
        columns = math.ceil(main.shape[1]/tw)
        rectangles = {w.name:dng.raster_rect(main,w) for w in windows}
        needed = set()
        for x,y,w,h in rectangles.values():
            needed.update(row*columns+col for row in range(y//th,(y+h-1)//th+1) for col in range(x//tw,(x+w-1)//tw+1))
        for index in sorted(needed):
            handle.seek(page.dataoffsets[index]); payload=handle.read(page.databytecounts[index])
            if page.compression == 52546:
                source,target=scratch/"tile.jxl",scratch/"tile.ppm"
                source.write_bytes(payload)
                kwargs={"creationflags":subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name=="nt" else {}
                result=subprocess.run([str(djxl),str(source),str(target),"--bits_per_sample=16","--num_threads=1"],capture_output=True,timeout=30,**kwargs)
                if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace"))
                mapped=read_ppm(target);tile=np.array(mapped,dtype=np.uint16);mapped._mmap.close()
                target.unlink();source.unlink()
            else:
                kwargs={"_fullsize":True}
                if page.compression in (6,7,34892,33007):
                    kwargs.update(jpegtables=page.jpegtables,jpegheader=page.keyframe.jpegheader)
                tile,_,_=page.decode(payload,index,**kwargs)
                tile=np.asarray(tile).reshape(-1,th,tw,3)[0]
            tx,ty=(index%columns)*tw,(index//columns)*th
            for name,(x,y,w,h) in rectangles.items():
                x0,y0=max(tx,x),max(ty,y);x1,y1=min(tx+tw,x+w),min(ty+th,y+h)
                if x1<=x0 or y1<=y0: continue
                output[name][y0-y:y1-y,x0-x:x1-x]=tile[y0-ty:y1-ty,x0-tx:x1-tx]
                filled[name]+=(y1-y0)*(x1-x0)
        for w in windows:
            if filled[w.name] != w.width*w.height: raise ValueError("Incomplete DNG crop coverage")
        return output


def audit_route(qualification_path, level, args):
    old=read(qualification_path)
    records=[]
    for record in old["records"]:
        print(level,record["scan_set"],record["set_id"],flush=True)
        encode=record["encode"];candidate=Path(encode["candidate"])
        current_hash=sha256_file(candidate)
        if current_hash != encode["candidate_sha256"]: raise ValueError(f"Candidate differs from technical evidence: {candidate}")
        source=resolve_source(encode["source_dng"],args.archive)
        raw=resolve_source(encode["raw61"],args.archive)
        source_meta,candidate_meta=dng.dng_metadata(source),dng.dng_metadata(candidate)
        differences=dng.metadata_diff_rows_for_pair(stem=source.stem,label=record["scan_set"]+"/"+record["set_id"],
                         level=level,source_meta=source_meta,candidate_meta=candidate_meta)
        def extra_tags(path):
            with tifffile.TiffFile(path) as t:
                page=dng.find_main_image(t).page
                return {name:dng.tag_value_from_pages([page,t.pages[0]],name) for name in
                        ("BlackLevel","BlackLevelRepeatDim","BlackLevelDeltaH","BlackLevelDeltaV","LinearizationTable",
                         "AsShotWhiteXY","AnalogBalance","DefaultScale","BaselineExposure","BaselineNoise","BaselineSharpness",
                         "ActiveArea","OpcodeList1","OpcodeList3","NoiseProfile","Orientation")}
        first,second=extra_tags(source),extra_tags(candidate)
        for key,value in first.items():
            if fingerprint(value)!=fingerprint(second[key]):
                differences.append({"field":key,"interpretation":"review_preservation_change",
                                    "source_value_sha256":fingerprint(value),"candidate_value_sha256":fingerprint(second[key])})
        preservation=[r for r in differences if r.get("interpretation")=="review_preservation_change"]
        windows=dng.load_crop_plan_windows(args.crop_plan,record["scan_set"]+"|"+record["set_id"],tuple(source_meta["active_crop_size"]))
        source_crops=extract(source,windows,args.djxl,args.scratch)
        candidate_crops=extract(candidate,windows,args.djxl,args.scratch)
        camera=[]
        for w in windows:
            a,b=source_crops[w.name],candidate_crops[w.name]
            diff=b.astype(np.float64)-a
            exact=bool(np.array_equal(a,b))
            if level=="lossless" and not exact: raise ValueError("Lossless DNG changed camera samples")
            camera.append({"name":w.name,"active_xywh":[w.x,w.y,w.width,w.height],"samples":int(a.size),
                           "pixel_exact":exact,"max_error_camera_codes":float(np.abs(diff).max()),
                           "mae_camera_codes":float(np.abs(diff).mean()),"rmse_camera_codes":float(np.sqrt(np.mean(diff*diff))),
                           "source_pixel_sha256":__import__('hashlib').sha256(a.astype('<u2').tobytes()).hexdigest(),
                           "candidate_pixel_sha256":__import__('hashlib').sha256(b.astype('<u2').tobytes()).hexdigest()})
        decoded=record["full_segment_decode"]
        adobe=record["adobe_dng_converter"]
        if decoded["status"]!="decoded" or adobe["status"]!="accepted":raise ValueError("Technical evidence is incomplete")
        name=record["set_id"]
        cohort="historical_f8_target" if name=="_DSC6577" else "diagnostic_flat_field" if name=="_DSC6598" else "secondary_sequence_or_uncompressed" if name in ("_DSC6793","_DSC6814") else "primary_compressed_independent"
        records.append({"scan_set":record["scan_set"],"set_id":name,"cohort":cohort,"level":level,
                        "candidate_bytes":candidate.stat().st_size,"candidate_sha256":current_hash,
                        "source_bytes":source.stat().st_size,"source_sha256":sha256_file(source),
                        "raw61_bytes":raw.stat().st_size,"raw61_sha256":sha256_file(raw),
                        "within_200_mib":candidate.stat().st_size<=200*2**20,"preservation_review_changes":len(preservation),
                        "technical_pass":not preservation,
                        "metadata_diff":differences,"camera_sample_metrics":camera,
                        "full_segment_decode":{"segments":decoded["segments"],"status":"decoded","evidence":"reused for identical candidate SHA-256"},
                        "adobe_acceptance":{"status":"accepted and rewritten","evidence":"reused for identical candidate SHA-256"},
                        "original_evidence_date":old["generated_at_utc"]})
    return {"level":level,"records":records,"original_qualification_sha256":sha256_file(qualification_path),
            "summary":{"files":len(records),"technical_passed":sum(r["technical_pass"] for r in records),"within_200_mib":sum(r["within_200_mib"] for r in records),
                       "exact_in_all_checked_crops":sum(all(c["pixel_exact"] for c in r["camera_sample_metrics"]) for r in records),
                       "cohort_frames":dict(Counter(r["cohort"] for r in records))}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--lossy",type=Path,required=True)
    p.add_argument("--lossless",type=Path,required=True)
    p.add_argument("--crop-plan",type=Path,required=True)
    p.add_argument("--djxl",type=Path,required=True)
    p.add_argument("--scratch",type=Path,required=True)
    p.add_argument("--output",type=Path,default=ROOT/"site/data/dng-evidence.json")
    args=p.parse_args();args.scratch.mkdir(parents=True,exist_ok=True)
    payload={"schema":3,"domain":"Integer camera samples; no display ICC, gamma or CIE color-difference interpretation",
             "scope":"16 historical PS16 sources, including the superseded f/8 target and a flat-field diagnostic; replacement f/4.5 target is absent",
             "withdrawn_claims":["Camera RGB CIEDE2000 estimates","Ratios against rendered RAW61 errors","15/16 archive-value qualification","Combining technical readability with perceptual quality"],
             "remaining_quality_question":"A common validated end-to-end DNG render and inversion comparison is required for a RAW61 image-quality advantage",
             "provenance":{"script_sha256":sha256_file(Path(__file__)),"dng_reader_sha256":sha256_file(ROOT/"scripts/run_dng_jxl_verification.py"),
                           "djxl_sha256":sha256_file(args.djxl),"decoder":"libjxl CLI, one thread per selected tile","crop_plan_sha256":sha256_file(args.crop_plan),
                           "tifffile":tifffile.__version__,"numpy":np.__version__},
             "routes":[audit_route(args.lossy,"d001",args),audit_route(args.lossless,"lossless",args)]}
    payload["evidence_id"]="dng-"+fingerprint(payload)[:16]
    atomic_write_json(args.output,payload)
    print(payload["evidence_id"],flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
