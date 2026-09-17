"""Map the public experiment declaration to owner-provided private artifacts.

The output is an ignored local inventory. No private path is published. Source
and encode contents are audited by rebuild_verified_report.py before adoption.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from incremental_cache import atomic_write_json
from run_local_scan_study import slugify


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def create(args):
    output=args.results/"private_inventory.json"
    if output.exists():raise ValueError("An inventory already exists; preserve it or choose a new results directory")
    design=read(ROOT/"metadata/verified_experiment.json")
    manifests={}
    for path in (args.archive/"input").glob("*/scan_manifest.json"):
        data=read(path);manifests[slugify(data.get("scan_root_name",path.parent.name))]=(path,data)
    frames=[]
    for item in design["frames"]:
        slug,set_id=item["slug"],item["set_id"]
        manifest_path,manifest=manifests[slug]
        capture=next(c for c in manifest["capture_sets"] if c["set_id"]==set_id)
        raw=capture.get("single_raw")
        if not raw:
            group=next(g for g in manifest["raw_pixelshift_groups"] if Path(g["raw_files"][0]).stem in set_id)
            raw=group["raw_files"][0]
        is_f45=item["cohort"]=="secondary_same_sequence_target"
        render_root=args.f45_root/"rawtherapee_renders_f45" if is_f45 else args.archive/"outputs/rawtherapee_renders"
        encoded_root=args.f45_root/"rendered_ps16_jxl_matrix_f45" if is_f45 else args.rgb16_root
        render=render_root/slug/set_id/"ps16.tif"
        reference=render if is_f45 else encoded_root/slug/set_id/"ps16_reference.ppm"
        frame={"scan_set":item["scan_set"],"slug":slug,"set_id":set_id,"cohort":item["cohort"],
               "source_manifest":str(manifest_path),"source_capture":capture,"raw_source":str(manifest_path.parent/raw),
               "dng_source":str(manifest_path.parent/capture["pixelshift16_dng"]),"reference":str(reference),
               "source_render":str(render),"raw_render":str(render.with_name("raw61.tif")),
               "candidates":{level:str(encoded_root/slug/set_id/level/"ps16.jxl") for level in design["levels"]},"crops":[]}
        for crop in item["crops"]:
            path=ROOT/"site/assets/review-viewers"/slug/set_id/crop["name"]/"metadata.json"
            metadata=read(path)
            if metadata["crop"]!=crop["xywh"]:raise ValueError("Public crop selection changed")
            frame["crops"].append({"name":crop["name"],"xywh":crop["xywh"],"metadata":str(path),"old_metadata":metadata})
        for path in [frame[k] for k in ("raw_source","dng_source","reference","source_render","raw_render")]+list(frame["candidates"].values()):
            if not Path(path).is_file():raise FileNotFoundError(path)
        frames.append(frame)
    atomic_write_json(output,{"schema":3,"frames":frames})
    print("Created private inventory for",len(frames),"frames")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--rgb16-root",type=Path,required=True)
    p.add_argument("--f45-root",type=Path,required=True)
    p.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    create(p.parse_args());return 0


if __name__=="__main__":raise SystemExit(main())
