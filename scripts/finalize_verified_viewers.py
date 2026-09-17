"""Finalize public viewer metadata after every frame has completed.

This downstream export step removes legacy fields without invalidating measured
pixels. Completion receipts bind both the analysis and the metadata exporter.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from incremental_cache import atomic_write_json,sha256_file

FIELDS={"schema","scan_set","set_id","cohort","crop","crop_name","analysis_recipe_sha256","asset_manifest",
        "browser_transform_recipe","build_inputs","default_transform","images_by_transform","labels",
        "local_raw61_alignment","overviews","overviews_by_transform","raw61_exposure_match","raw61_scope_note",
        "rgb16","source_profile","thumbnail","view_modes"}


def retry_sharing_violation(operation):
    """Briefly retry Windows sharing locks; never mask access or data errors."""
    delays=(0,.15,.5,1,2)
    for index,delay in enumerate(delays):
        if delay:time.sleep(delay)
        try:return operation()
        except OSError as error:
            if getattr(error,"winerror",None) not in (32,33) or index==len(delays)-1:raise


def pack_pixels(raw):
    if len(raw)%2:raise ValueError("Incomplete RGB16 sample")
    return gzip.compress(raw[::2]+raw[1::2],compresslevel=6,mtime=0)


def unpack_pixels(packed):
    planes=gzip.decompress(packed)
    if len(planes)%2:raise ValueError("Incomplete byte-plane payload")
    half=len(planes)//2;raw=bytearray(len(planes))
    raw[::2]=planes[:half];raw[1::2]=planes[half:]
    return bytes(raw)


def export_pixels(metadata,path,cache):
    mapping={};relocated={}
    for asset in metadata["asset_manifest"].values():
        original_sha=asset.get("decoded_sha256",asset["sha256"])
        original_bytes=asset.get("decoded_bytes",asset["bytes"])
        original_name=asset["file"].removesuffix(".gz")
        original=path.parent/original_name
        retained=cache/(original_sha+".rgb16le")
        source=original if original.is_file() else retained
        raw=source.read_bytes()
        if len(raw)!=original_bytes or hashlib.sha256(raw).hexdigest()!=original_sha:raise ValueError("Original viewer pixels changed")
        packed=pack_pixels(raw)
        if unpack_pixels(packed)!=raw:raise ValueError("Lossless transport round-trip failed")
        target=path.parent/(original_name+".gz")
        partial=target.with_suffix(target.suffix+".partial");partial.write_bytes(packed)
        retry_sharing_violation(lambda:partial.replace(target))
        mapping[original_name]=target.name
        asset.update({"file":target.name,"bytes":len(packed),"sha256":sha256_file(target),
                      "decoded_bytes":original_bytes,"decoded_sha256":original_sha})
        # Keep the uncompressed analysis cache outside the published directory.
        # Both resolved targets are explicitly constrained to this workspace.
        if not original.resolve().is_relative_to((ROOT/"site/assets/review-viewers").resolve()) or not retained.resolve().is_relative_to((ROOT/"results").resolve()):
            raise ValueError("Pixel cache relocation escaped the declared workspace")
        if original.is_file():
            if retained.is_file():
                if sha256_file(retained)!=original_sha:raise ValueError("Conflicting retained pixel cache")
                retry_sharing_violation(original.unlink)
            else:retry_sharing_violation(lambda:original.replace(retained))
        relocated[original.relative_to(ROOT).as_posix()]=retained.relative_to(ROOT).as_posix()
    metadata["rgb16"]["sources"]={k:mapping.get(v.removesuffix(".gz"),v) for k,v in metadata["rgb16"]["sources"].items()}
    metadata["rgb16"]["transport"]="gzip-byteplanes-v1"
    return relocated


def sanitize(metadata):
    if metadata.get("schema")!=3:raise ValueError("Cannot finalize legacy viewer metadata")
    result={k:v for k,v in metadata.items() if k in FIELDS}
    result["raw61_scope_note"]=result.get("raw61_scope_note","").replace("The left image is","The RAW61 baseline is")
    return result


def apply_journal(journal):
    data=json.loads(journal.read_text(encoding="utf-8"))
    for relative,payload in data["writes"]:
        path=ROOT/relative
        if not path.resolve().is_relative_to(ROOT.resolve()):raise ValueError("Unsafe export journal path")
        atomic_write_json(path,payload)
    journal.unlink()


def finalize(results):
    from viewer_overviews import overview_record, bind_overviews
    site=ROOT/"site"
    overviews=json.loads((site/"data/overview-evidence.json").read_text(encoding="utf-8"))
    for relative,expected in overviews["asset_hashes"].items():
        if not (site/relative).resolve().is_relative_to(site.resolve()) or sha256_file(site/relative)!=expected:
            raise ValueError("Missing or changed full-frame overview")
    inventory=json.loads((results/"private_inventory.json").read_text(encoding="utf-8"))["frames"]
    jobs=[]
    cache=results/"viewer-pixels";cache.mkdir(parents=True,exist_ok=True)
    # Finish any interrupted commit before validating the complete inventory.
    for journal in results.glob("*/*/viewer-export-pending.json"):
        apply_journal(journal)
    # Validate the complete set before changing any public metadata.
    for f in inventory:
        receipt=results/f["slug"]/f["set_id"]/"complete.json"
        data=json.loads(receipt.read_text(encoding="utf-8"))
        if len(data["metadata_hashes"])!=len(f["crops"]):raise ValueError("Incomplete viewer set")
        for relative,expected in data["metadata_hashes"].items():
            path=ROOT/relative
            if sha256_file(path)!=expected:raise ValueError("Viewer metadata changed outside the pipeline")
            overview_record(json.loads(path.read_text(encoding="utf-8")),overviews)
        jobs.append((receipt,data))
    for receipt,data in jobs:
        print("PACK",receipt.parent.parent.name+"/"+receipt.parent.name,flush=True)
        relocated={};writes=[]
        for relative in data["metadata_hashes"]:
            path=ROOT/relative
            metadata=json.loads(path.read_text(encoding="utf-8"))
            relocated.update(export_pixels(metadata,path,cache))
            metadata=sanitize(metadata)
            bind_overviews(metadata,overviews,path,site)
            writes.append((relative,metadata))
            staged=receipt.with_name("viewer-export-staged.json")
            atomic_write_json(staged,metadata)
            data["metadata_hashes"][relative]=sha256_file(staged)
            staged.unlink()
        for checkpoint in receipt.parent.glob("d[0-9][0-9][0-9].json"):
            record=json.loads(checkpoint.read_text(encoding="utf-8"))
            record["asset_hashes"]={relocated.get(k,k):v for k,v in record["asset_hashes"].items()}
            writes.append((checkpoint.relative_to(ROOT).as_posix(),record))
        data["metadata_export"]={"script_sha256":sha256_file(Path(__file__)),"schema":3}
        writes.append((receipt.relative_to(ROOT).as_posix(),data))
        journal=receipt.with_name("viewer-export-pending.json")
        atomic_write_json(journal,{"writes":writes})
        apply_journal(journal)
    return sum(len(d["metadata_hashes"]) for _,d in jobs)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    print("Finalized",finalize(p.parse_args().results),"viewer manifests");return 0


if __name__=="__main__":raise SystemExit(main())
