"""Bounded, ICC-managed tonal-agreement audit of two retained combiner cases.

This compares render agreement with the first source ARW. That noisy, lower
resolution anchor cannot establish which combiner preserves more scene latitude.
"""
from __future__ import annotations

import argparse
from collections import Counter
import io
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
from PIL import Image,ImageCms,ImageDraw
from break_even_image_tools import read_rgb_image,box_blur_luma,structure_metrics
from image_color import image_profile
from report_transforms import sample_raw_crop,align_scope,recipe_for,transform
from incremental_cache import sha256_file,atomic_write_json,fingerprint
from rebuild_verified_report import run,close_image,atomic_bytes,check_resources


def compare(ref,anchor,sony,profile):
    anchor,ar=align_scope(ref,anchor,profile)
    sony,sr=align_scope(ref,sony,profile)
    if not ar["applied"] or not sr["applied"]:
        raise ValueError("Uncertain combiner/anchor registration; inspection required")
    rectangles=[r["valid_xywh"] for r in (ar,sr)]
    x,y=max(r[0] for r in rectangles),max(r[1] for r in rectangles)
    right,bottom=min(r[0]+r[2] for r in rectangles),min(r[1]+r[3] for r in rectangles)
    # Additional low-pass radius is excluded from the evaluated support.
    x,y,right,bottom=x+4,y+4,right-4,bottom-4
    ref,anchor,sony=[a[y:bottom,x:right] for a in (ref,anchor,sony)]
    weights=profile.matrix[1];anchor_y=anchor @ weights
    lo,hi=np.percentile(anchor_y,[20,80]);mask=(anchor_y>=lo)&(anchor_y<=hi)&(anchor_y>1e-5)
    gains={};values={}
    for key,arr in (("pixelshift2dng",ref),("sony_arq",sony)):
        luminance=arr @ weights
        valid=mask&(luminance>1e-5)
        gain=float(np.median(anchor_y[valid]/luminance[valid]))
        if not .5<gain<2:raise ValueError("Unexpected exposure fit")
        gains[key]={"gain":gain,"ev":math.log2(gain),"fit_pixels":int(valid.sum())}
        values[key]=arr*gain
    bounds=np.percentile(anchor_y,[.2,12,20,80,88,99.8])
    anchor_low=box_blur_luma(anchor_y,4)
    ranges={}
    for name,(lo,hi) in zip(("shadow","midtone","highlight"),zip(bounds[::2],bounds[1::2])):
        mask=(anchor_y>=lo)&(anchor_y<=hi)
        mask[:4]=False;mask[-4:]=False;mask[:,:4]=False;mask[:,-4:]=False
        errors={key:float(np.sqrt(np.mean((box_blur_luma(arr @ weights,4)[mask]-anchor_low[mask])**2))) for key,arr in values.items()}
        ranges[name]={"anchor_y_bounds":[float(lo),float(hi)],"pixels":int(mask.sum()),"rmse":errors,
                      "closer_to_anchor":min(errors,key=errors.get) if abs(errors["pixelshift2dng"]-errors["sony_arq"])>1e-12 else "tie"}
    detail={key:structure_metrics(anchor,arr,luma_weights=tuple(weights)).detail_correlation for key,arr in values.items()}
    metrics={"registration":{"anchor":ar,"sony":sr},"valid_xywh":[x,y,right-x,bottom-y],
             "exposure_match":gains,"range_errors":ranges,"detail_correlation":detail,
             "detail_closer_to_anchor":max(detail,key=detail.get)}
    return [anchor,values["pixelshift2dng"],values["sony_arq"]],metrics


def write_panel(path,images,profile):
    recipe=recipe_for(images[0],profile)
    output=Image.new("RGB",(1200,1272),"#f6f7f8");draw=ImageDraw.Draw(output)
    for row,mode in enumerate(("identity","shadow_recovery_luma_p12","highlight_separation_luma_p88_p998")):
        for col,(arr,label) in enumerate(zip(images,("Source ARW anchor","PixelShift2DNG","Sony ARQ"))):
            display=profile.display(transform(arr,mode,recipe))
            tile=Image.fromarray(np.rint(np.clip(display,0,1)*255).astype(np.uint8))
            tile.thumbnail((400,400),Image.Resampling.LANCZOS)
            draw.text((col*400+8,row*424+8),label+" | "+("normal","shadow","highlight")[row],fill="#1d2329")
            output.paste(tile,(col*400,row*424+24))
    buffer=io.BytesIO();output.save(buffer,format="PNG",icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    atomic_bytes(path,buffer.getvalue())


def build(args):
    prior=json.loads((ROOT/"metadata/combiner_crop_plan.json").read_text(encoding="utf-8"))
    sources={"adox-vlad":("kodak5035_h190_1983","_DSC6582-_DSC6597","input/_superseded/adox_vlad_resolution_target_f8/_DSC6582.ARW"),
             "kodak-gold":("kodak_gold_200_5_1997","_DSC6798-_DSC6813","input/Kodak Gold 200-5 1997/_DSC6798.ARW")}
    # The previous public labels vary; sequence identity is the stable join.
    cases=[];assets={}
    for old in prior["cases"]:
        spec=next(v for v in sources.values() if v[1]==old["sequence"])
        slug,sequence,raw_relative=spec
        source=args.archive/raw_relative
        directory=args.archive/"outputs/ied_merge_control"/slug/sequence
        anchor=args.scratch/(sequence+"-anchor.tif")
        receipt=anchor.with_suffix(".json")
        identity={"source_sha256":sha256_file(source),"profile_sha256":sha256_file(ROOT/"profiles/rawtherapee/neutral-render.pp3"),
                  "rawtherapee_sha256":sha256_file(args.rawtherapee)}
        old_receipt=json.loads(receipt.read_text()) if receipt.is_file() else {}
        if not anchor.is_file() or old_receipt.get("identity")!=identity or old_receipt.get("output_sha256")!=sha256_file(anchor):
            check_resources(args.scratch,4)
            print("RENDER ANCHOR",sequence,flush=True)
            run([str(args.rawtherapee),"-o",str(anchor),"-p",str(ROOT/"profiles/rawtherapee/neutral-render.pp3"),"-t","-Y","-c",str(source)],1800)
            atomic_write_json(receipt,{"identity":identity,"output_sha256":sha256_file(anchor)})
        paths={"anchor":anchor,"pixelshift2dng":directory/"pixelshift2dng_ps16_neutral.tif","sony_arq":directory/"ied_ps16_neutral.tif"}
        profiles={k:image_profile(p) for k,p in paths.items()}
        profile=profiles["pixelshift2dng"]
        arrays={k:read_rgb_image(p) for k,p in paths.items()}
        crops=[]
        try:
            for item in old["crops"]:
                x,y,w,h=item["crop"]
                ref=profile.linearize(arrays["pixelshift2dng"][y:y+h,x:x+w])
                others={k:sample_raw_crop(arrays[k],profiles[k],(x,y,w,h),arrays["pixelshift2dng"].shape,(0,0)) @
                        (np.linalg.inv(profile.matrix) @ profiles[k].matrix).T for k in ("anchor","sony_arq")}
                images,metrics=compare(ref,others["anchor"],others["sony_arq"],profile)
                path=args.site/"assets/combiner-verified"/(old["key"]+"-"+item["name"]+".png")
                write_panel(path,images,profile)
                relative=path.relative_to(args.site).as_posix();assets[relative]=sha256_file(path)
                crops.append({"name":item["name"],"crop_xywh":item["crop"],"metrics":metrics,"figure":relative})
            cases.append({"key":old["key"],"sequence":sequence,"label":old["label"]+ (" (historical f/8 capture)" if sequence.startswith("_DSC6582") else ""),
                          "render_provenance":"Fresh first-ARW anchor; retained neutral RawTherapee 5.12 combiner renders adopted by content hash",
                          "anchor_recipe":identity,"source_render_hashes":{k:sha256_file(p) for k,p in paths.items()},
                          "profiles":{k:v.recipe() for k,v in profiles.items()},"crops":crops})
        finally:
            for a in arrays.values():close_image(a)
    all_crops=[c for case in cases for c in case["crops"]]
    summary={"sequences":len(cases),"crops":len(all_crops),"closer_to_anchor_counts":{band:dict(Counter(c["metrics"]["range_errors"][band]["closer_to_anchor"] for c in all_crops)) for band in ("shadow","midtone","highlight")}}
    payload={"schema":3,"scope":"Five approved crops from two historical sequences; one f/8 target and one Kodak Gold frame",
             "interpretation":"Tonal and spatial agreement with one source ARW after a shared-domain registration and scalar midtone exposure fit. The anchor is noisy and lower resolution; these comparisons cannot rank recovered scene latitude or absolute image quality",
             "method":"Actual embedded ICC TRCs and XYZ D50 conversion; linear resampling; common valid support; 9x9 float64 low-pass tone error. Detail uses separate 5x5 high-pass correlation. Exposure fitting applies only to this bounded combiner audit",
             "recipe_code":{p:sha256_file(ROOT/p) for p in ("scripts/rebuild_combiner_evidence.py","metadata/combiner_crop_plan.json","profiles/rawtherapee/neutral-render.pp3","src/image_color.py","src/report_transforms.py","src/break_even_image_tools.py")},
             "summary":summary,"cases":cases,"asset_hashes":assets}
    payload["evidence_id"]="combiner-"+fingerprint(payload)[:16]
    atomic_write_json(args.site/"data/combiner-evidence.json",payload)
    return payload


def main():
    from run_responsive import lower_priority
    lower_priority()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--scratch",type=Path,required=True)
    p.add_argument("--site",type=Path,default=ROOT/"site")
    p.add_argument("--rawtherapee",type=Path,default=Path(r"C:\Program Files\RawTherapee\5.12\rawtherapee-cli.exe"))
    args=p.parse_args();args.scratch.mkdir(parents=True,exist_ok=True)
    print(build(args)["summary"])
    return 0


if __name__=="__main__":raise SystemExit(main())
