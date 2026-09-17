"""Audit metadata-only repairs, capture color inputs and RAW viewer quantization."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
from incremental_cache import sha256_file,atomic_write_json,fingerprint
from rebuild_verified_report import run,close_image,LEVELS
from break_even_image_tools import read_rgb_image,highpass_luma
from image_color import image_profile,RgbProfile
from report_transforms import sample_raw_crop,transform,MODES


def codestream_sha256(path):
    digest=hashlib.sha256();parts=0
    with Path(path).open("rb") as f:
        signature=f.read(12)
        if signature[:2]==b'\xff\x0a':
            f.seek(0)
            for block in iter(lambda:f.read(8*2**20),b''):digest.update(block)
            return digest.hexdigest()
        if signature!=b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a':raise ValueError("Invalid JPEG XL container")
        while True:
            header=f.read(8)
            if not header:break
            if len(header)!=8:raise ValueError("Truncated JPEG XL box")
            length,kind=struct.unpack('>I4s',header);header_size=8
            if length==1:length=struct.unpack('>Q',f.read(8))[0];header_size=16
            if length==0:length=Path(path).stat().st_size-f.tell()+header_size
            remaining=length-header_size
            if remaining<0:raise ValueError("Invalid JPEG XL box length")
            if kind in (b'jxlc',b'jxlp'):
                parts+=1
                if kind==b'jxlp':f.read(4);remaining-=4
                while remaining:
                    block=f.read(min(8*2**20,remaining))
                    if not block:raise ValueError("Truncated JPEG XL codestream")
                    digest.update(block);remaining-=len(block)
            else:f.seek(remaining,1)
    if not parts:raise ValueError("No JPEG XL image codestream")
    return digest.hexdigest()


def audit(args):
    inventory=json.loads((args.results/"private_inventory.json").read_text(encoding="utf-8"))["frames"]
    config=configparser.ConfigParser();config.read(ROOT/"profiles/rawtherapee/neutral-render.pp3",encoding="utf-8")
    settings={section:dict(config[section]) for section in ("White Balance","Exposure","Color Management","HLRecovery")}
    frames=[]
    for item in inventory:
        print("LINEAGE",item["set_id"],flush=True)
        directory=args.results/item["slug"]/item["set_id"]
        saved=json.loads((directory/"source_audit.json").read_text(encoding="utf-8"))
        captures={}
        for role in ("raw_source","dng_source"):
            tags=json.loads(run([str(args.exiftool),"-j","-n","-Make","-Model","-ExposureTime","-FNumber","-ISO",
                                "-WhiteBalance","-WB_RGGBLevels","-WB_RGGBLevelsAsShot","-AsShotNeutral",
                                "-ColorMatrix1","-ColorMatrix2","-BaselineExposure",item[role]],120).stdout)[0]
            tags.pop("SourceFile",None);captures[role]=tags
        encodes=[];measured={}
        for level in LEVELS:
            record=json.loads((directory/(level+".json")).read_text(encoding="utf-8"))
            measured[level]=record
            first,second=record["audit"]["original"],record["audit"]["released"]
            original_hash=codestream_sha256(first["path"])
            if original_hash!=codestream_sha256(second["path"]):raise ValueError("Metadata repair changed the image codestream")
            encodes.append({"level":level,"original_file_sha256":first["sha256"],"released_file_sha256":second["sha256"],
                            "image_codestream_sha256":original_hash,"metadata_only_repair":True})
        reference_record=json.loads((directory/"d003.json").read_text(encoding="utf-8"))
        scopes=reference_record["analysis_recipe"]["scopes"]
        broad=scopes[0]["alignment"]
        shift=(broad["shift_x_px"]*10,broad["shift_y_px"]*10) if broad["applied"] else (0,0)
        profile=image_profile(Path(item["raw_render"]))
        raw=read_rgb_image(Path(item["raw_render"]))
        quantization=[]
        try:
            for crop in item["crops"]:
                scope=next(s for s in scopes if s["name"]==crop["name"])
                x,y,w,h=crop["xywh"];gx,gy=shift
                if not (x-gx>8 and y-gy>8 and x+w-gx<saved["shape"][1]-8 and y+h-gy<saved["shape"][0]-8):
                    raise ValueError("Native RAW resampling footprint reaches the source boundary")
                linear=sample_raw_crop(raw,profile,tuple(crop["xywh"]),tuple(saved["shape"]),shift)
                alignment=scope["alignment"]
                ix,iy=(int(alignment["shift_x_px"]),int(alignment["shift_y_px"])) if alignment["applied"] else (0,0)
                linear=np.roll(linear,(iy,ix),(0,1))
                codes=profile.encode_u16(linear)
                exported=Path(crop["metadata"]).parent/"raw61.rgb16le"
                if not exported.is_file():exported=args.results/"viewer-pixels"/(hashlib.sha256(codes.astype('<u2').tobytes()).hexdigest()+".rgb16le")
                if hashlib.sha256(codes.astype('<u2').tobytes()).hexdigest()!=sha256_file(exported):
                    raise ValueError("RAW viewer source differs from measured resampling")
                quantized=profile.linearize(codes)
                errors={}
                for mode in MODES:
                    a,b=[np.rint(np.clip(profile.display(transform(arr,mode,scope["recipe"])),0,1)*255) for arr in (linear,quantized)]
                    errors[mode]=float(np.max(np.abs(a-b)))
                metadata=json.loads(Path(crop["metadata"]).read_text(encoding="utf-8"))
                def pixels(asset):
                    source=Path(crop["metadata"]).parent/asset["file"].removesuffix('.gz')
                    if not source.is_file():source=args.results/"viewer-pixels"/(asset.get("decoded_sha256",asset["sha256"])+".rgb16le")
                    return np.frombuffer(source.read_bytes(),dtype='<u2').reshape(h,w,3)
                vx,vy,vw,vh=alignment["valid_xywh"]
                def hp(arr):return highpass_luma(arr[vy:vy+vh,vx:vx+vw],weights=tuple(profile.matrix[1]))
                reference_hp=hp(profile.linearize(pixels(metadata["asset_manifest"]["reference"])))
                raw_hp=hp(linear)
                def loss(cand,interior=False):
                    r,c=(reference_hp[2:-2,2:-2],cand[2:-2,2:-2]) if interior else (reference_hp,cand)
                    energy=float(np.sqrt(np.mean(r*r)))
                    return float(np.sqrt(np.mean((c-r)**2)))/energy if energy>2**-23 else None
                raw_loss,raw_interior=loss(raw_hp),loss(raw_hp,True)
                boundaries=[]
                for level in LEVELS:
                    asset=metadata["asset_manifest"]["jxl_"+level];p=asset["profile"]
                    candidate_profile=RgbProfile(p["name"],p["icc_sha256"],np.asarray(p["rgb_to_xyz_d50"]),tuple(p["curves"]))
                    candidate=(candidate_profile.linearize(pixels(asset)) @ np.asarray(p["linear_to_reference"]).T).astype(np.float32)
                    candidate_hp=hp(candidate);original_loss,interior_loss=loss(candidate_hp),loss(candidate_hp,True)
                    published=next(m for m in measured[level]["measurements"] if m["scope"]==crop["name"] and m["candidate"]["transform"]=="identity")
                    for value,role in ((original_loss,"candidate"),(raw_loss,"raw61")):
                        if value is not None and not math.isclose(value,published[role]["structure_loss"],rel_tol=1e-8,abs_tol=1e-10):
                            raise ValueError("Retained crop cannot reproduce its published native structure metric")
                    boundaries.append({"level":level,"candidate_loss":original_loss,"raw61_loss":raw_loss,
                                       "candidate_interior_loss":interior_loss,"raw61_interior_loss":raw_interior,
                                       "relative_screen_changed":None if any(v is None for v in (original_loss,interior_loss,raw_loss,raw_interior)) else
                                           (original_loss<=raw_loss)!=(interior_loss<=raw_interior)})
                quantization.append({"crop":crop["name"],"source_resampling_support_inside_bounds":True,
                                     "outside_unit_range_channel_fraction":float(np.mean((linear<0)|(linear>1))),
                                     "max_linear_error":float(np.max(np.abs(linear-quantized))),"max_display_code_error_by_mode":errors,
                                     "native_highpass_boundary_sensitivity":boundaries})
        finally:close_image(raw)
        frames.append({"scan_set":item["scan_set"],"set_id":item["set_id"],"capture_color_and_exposure_metadata":captures,
                       "encodes":encodes,"raw_viewer_quantization":quantization})
    payload={"schema":3,"frames":frames,"declared_render_preset":settings,
             "preset_sha256":sha256_file(ROOT/"profiles/rawtherapee/neutral-render.pp3"),
             "adoption":"Retained encodes are adopted by declared source/candidate mapping, RGB16 dimensions, embedded profile, full decode and measured image agreement with the pixel-verified source. Their original encoder jobs did not record input content hashes. Current source and candidate hashes freeze this reviewed snapshot; no claim of historical cryptographic provenance or byte-identical re-encoding is made.",
             "render_limit":"The neutral preset uses camera white balance and camera input profiles. RAW and DNG can therefore resolve different color and exposure interpretation. Capture metadata is disclosed, but retained TIFFs do not preserve a complete effective RawTherapee parameter dump. The primary result compares these retained rendered workflows; it does not isolate sensor sampling alone.",
             "viewer_limit":"Measurements use floating-point linear RAW resampling. Browser RAW buffers quantize that result to unsigned RGB16; all resulting display differences and any out-of-range resampling values are disclosed per crop. Candidate and PS16 crop buffers retain their original decoded RGB16 codes.",
             "boundary_check":"Original native HP loss uses reflect padding at the boundary of the valid measurement crop. Sensitivity excludes two output pixels on every side after filtering, removing all padding-dependent values. Relative-screen changes and undefined low-energy ratios are disclosed for all native crops and distances; the frozen measurement recipe is not retuned",
             "recipe_code":{p:sha256_file(ROOT/p) for p in ("scripts/audit_render_lineage.py","src/image_color.py","src/report_transforms.py")}}
    payload["evidence_id"]="lineage-"+fingerprint(payload)[:16]
    atomic_write_json(args.output,payload)
    print(payload["evidence_id"])


def main():
    from run_responsive import lower_priority
    lower_priority()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    p.add_argument("--exiftool",type=Path,default=Path(r"C:\Program Files\ExifTool\ExifTool.exe"))
    p.add_argument("--output",type=Path,default=ROOT/"site/data/lineage-evidence.json")
    audit(p.parse_args());return 0


if __name__=="__main__":raise SystemExit(main())
