"""Verify retained sensor-domain bracket evidence without applying RGB fixes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from incremental_cache import sha256_file,fingerprint,atomic_write_json
from rebuild_verified_report import run
from run_controlled_exposure_latitude import summarize,pixel_shift_active,exposure_ev


def audit(args):
    retained=ROOT/"metadata/controlled_exposure_latitude.json"
    data=json.loads(retained.read_text(encoding="utf-8"))
    plan=json.loads((ROOT/"metadata/controlled_exposure_latitude_plan.json").read_text(encoding="utf-8"))
    if fingerprint(summarize(data["cases"]))!=fingerprint(data["summary"]):raise ValueError("Bracket summary differs from its rows")
    source_states=[]
    for case in data["cases"]:
        planned=next(c for c in plan["cases"] if c["key"]==case["key"])
        if sorted(planned["files"])!=sorted(f["file"] for f in case["frames"]):raise ValueError("Bracket identity mismatch")
        normal=next(f for f in case["frames"] if f["file"]==case["normal"])
        for frame in case["frames"]:
            path=args.source_root/frame["file"]
            row=json.loads(run([str(args.exiftool),"-j","-n","-ExposureTime","-ISO","-FNumber","-PixelShiftInfo",
                               "-DateTimeOriginal","-SubSecTimeOriginal",str(path)],120).stdout)[0]
            if abs(float(row["ExposureTime"])-frame["exposure_seconds"])>1e-8 or int(row["ISO"])!=frame["iso"]:
                raise ValueError("Bracket source metadata changed")
            timestamp=str(row["DateTimeOriginal"])+("."+str(row["SubSecTimeOriginal"]) if "SubSecTimeOriginal" in row else "")
            if timestamp!=frame["timestamp"]:raise ValueError(f"Capture timestamp differs for {frame['file']}")
            if pixel_shift_active(str(row.get("PixelShiftInfo",""))):raise ValueError("Expected single-shot frame")
            if abs(exposure_ev(frame["exposure_seconds"],normal["exposure_seconds"])-frame["computed_ev"])>1e-8:
                raise ValueError("Exposure normalization mismatch")
            source_states.append({"file":frame["file"],"bytes":path.stat().st_size,"sha256":sha256_file(path)})
    data.update({"schema":3,"review_note":"Retained sensor-domain results were not rerun: the repaired RGB/ICC helpers do not participate in this experiment. Capture membership, current source hashes, exposure metadata, timestamps, single-shot status and all summary aggregates were checked. Original-run source hashes were not recorded, so the new hashes identify the currently audited sources rather than prove byte identity at the historical run date.",
                 "source_states":source_states,"retained_evidence_sha256":sha256_file(retained),
                 "recipe_code":{"scripts/run_controlled_exposure_latitude.py":sha256_file(ROOT/"scripts/run_controlled_exposure_latitude.py"),
                                "scripts/audit_controlled_evidence.py":sha256_file(Path(__file__))},
                 "plan_sha256":sha256_file(ROOT/"metadata/controlled_exposure_latitude_plan.json")})
    data["evidence_id"]="controlled-"+fingerprint(data)[:16]
    atomic_write_json(args.output,data)
    print(data["evidence_id"],len(source_states),"source files checked")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--exiftool",type=Path,default=Path(r"C:\Program Files\ExifTool\ExifTool.exe"))
    p.add_argument("--output",type=Path,default=ROOT/"site/data/controlled-evidence.json")
    audit(p.parse_args());return 0


if __name__=="__main__":raise SystemExit(main())
