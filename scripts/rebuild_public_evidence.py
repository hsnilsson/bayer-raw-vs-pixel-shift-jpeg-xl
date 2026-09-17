"""Reproducible six-image ICC-managed JPEG XL edit-sensitivity experiment.

Public inputs only. A center crop is encoded once at each distance; the actual
decoder ICC is used for every measurement. No full-frame or raw-latitude claim.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
from PIL import Image, ImageCms, ImageDraw
import tifffile
from image_color import profile_from_icc, embedded_icc, D50, srgb_encode, SRGB
from report_transforms import recipe_for, measure, transform, MODES
from incremental_cache import atomic_write_json, sha256_file, fingerprint
from rebuild_verified_report import run, close_image, atomic_bytes
from break_even_image_tools import read_rgb_image
from run_public_latitude_v2 import PUBLIC_V2_INPUTS


def gray_to_rgb16(values: np.ndarray, icc: bytes, target_icc: bytes) -> tuple[np.ndarray, dict]:
    """Relative-colorimetric Gray gamma -> PCS D50 -> an explicit RGB profile.

    This corpus has one Gray gamma profile. Refuse other Gray curve/LUT forms
    rather than applying an undocumented fallback. Validate all 256 source
    levels against an independent LittleCMS conversion.
    """
    if icc[16:24] != b"GRAYXYZ " or values.dtype != np.uint8:
        raise ValueError("Expected the declared public Gray8 matrix/gamma input")
    tags = {}
    for i in range(struct.unpack_from(">I",icc,128)[0]):
        key,offset,length=struct.unpack_from(">4sII",icc,132+12*i)
        tags[key]=icc[offset:offset+length]
    curve=tags[b"kTRC"]
    if curve[:4]!=b"curv" or struct.unpack_from(">I",curve,8)[0]!=1 or b"A2B0" in tags:
        raise ValueError("Unsupported Gray profile; explicit CMS conversion required")
    gamma=struct.unpack_from(">H",curve,12)[0]/256
    target=profile_from_icc(target_icc)
    codes=np.arange(256,dtype=np.uint8).reshape(1,256)
    y=(codes.astype(np.float64)/255)**gamma
    linear=y[...,None]*(np.linalg.inv(target.matrix) @ D50)
    table=target.encode_u16(linear)[0]
    oracle=np.asarray(ImageCms.profileToProfile(Image.fromarray(codes),ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                ImageCms.ImageCmsProfile(io.BytesIO(target_icc)),outputMode="RGB",renderingIntent=1))
    error=float(np.max(np.abs(np.rint(table.astype(float)/257)-oracle[0])))
    if error>2: raise ValueError(f"Gray conversion differs from LittleCMS: {error}")
    return table[values], {"method":"Gray ICC gamma to relative PCS D50, then sRGB RGB16",
                          "source_gamma":gamma,"source_precision_bits":8,"littlecms_max_code_error":error}


def panel(path, reference, candidate, profile, recipe):
    tiles=[]
    labels=[]
    for name in ("identity","negative_density_hard_print"):
        for arr,label in ((reference,"Reference"),(candidate,"JXL d=0.05")):
            displayed=profile.display(transform(arr,name,recipe))
            tile=Image.fromarray(np.rint(np.clip(displayed,0,1)*255).astype(np.uint8))
            tile.thumbnail((480,480),Image.Resampling.LANCZOS)
            tiles.append(tile);labels.append(label+ (" | normal" if name=="identity" else " | hard inversion"))
    output=Image.new("RGB",(960,1024),"#f6f7f8");draw=ImageDraw.Draw(output)
    for i,(tile,label) in enumerate(zip(tiles,labels)):
        x,y=(i%2)*480,(i//2)*512
        draw.text((x+8,y+8),label,fill="#1d2329");output.paste(tile,(x,y+28))
    buffer=io.BytesIO();output.save(buffer,format="PNG",icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    atomic_bytes(path,buffer.getvalue())


def build(args):
    srgb_icc=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    records=[];figures={}
    for n,relative in enumerate(p.relative_to(ROOT) for p in PUBLIC_V2_INPUTS):
        source=args.inputs/relative
        print("PUBLIC",source.name,flush=True)
        with tifffile.TiffFile(source) as tif:
            shape=tif.pages[0].shape;dtype=tif.pages[0].dtype
        width,height=min(2048,shape[1]),min(2048,shape[0])
        x,y=(shape[1]-width)//2,(shape[0]-height)//2
        icc=embedded_icc(source)
        if len(shape)==2:
            original=tifffile.imread(source)[y:y+height,x:x+width]
            encoded,conversion=gray_to_rgb16(original,icc,srgb_icc);working_icc=srgb_icc
        else:
            mapped=read_rgb_image(source)
            original=np.array(mapped[y:y+height,x:x+width]);close_image(mapped)
            encoded=original.astype(np.uint16)*(257 if dtype.itemsize==1 else 1)
            conversion={"method":"Original RGB profile retained; RGB8 expanded exactly by 257 when applicable",
                        "source_precision_bits":dtype.itemsize*8}
            working_icc=icc
        directory=args.scratch/str(n);directory.mkdir(parents=True,exist_ok=True)
        ppm,profile_file=directory/"source.ppm",directory/"source.icc"
        ppm.write_bytes(f"P6\n{width} {height}\n65535\n".encode()+encoded.astype('>u2').tobytes())
        profile_file.write_bytes(working_icc)
        profile=profile_from_icc(working_icc);reference=profile.linearize(encoded);recipe=recipe_for(reference,profile)
        source_sidecar=source.with_suffix(source.suffix+".source.json")
        sidecar=json.loads(source_sidecar.read_text(encoding="utf-8"))
        if sidecar["sha256"]!=sha256_file(source):raise ValueError("Public source differs from its published provenance")
        case={"name":source.stem,"public_input":relative.as_posix(),"source_sha256":sha256_file(source),
              "source_profile_sha256":hashlib.sha256(icc).hexdigest(),"source_shape":list(shape),"crop_xywh":[x,y,width,height],
              "conversion":conversion,"working_profile":profile.recipe(),"recipe":recipe,
              "source_provenance":sidecar,"levels":[]}
        for distance in (0,.03,.05,.10):
            jxl,decoded,out_icc=directory/f"d{distance:.2f}.jxl",directory/"decoded.ppm",directory/"decoded.icc"
            run([str(args.tools/"cjxl.exe"),str(ppm),str(jxl),"--container=1","-x",f"icc_pathname={profile_file}",
                 "-e","7","-d",str(distance),"--num_threads=2"],300)
            run([str(args.tools/"djxl.exe"),str(jxl),str(decoded),"--bits_per_sample=16","--num_threads=2",f"--icc_out={out_icc}"],120)
            mapped=read_rgb_image(decoded);actual=np.array(mapped);close_image(mapped)
            actual_profile=profile_from_icc(out_icc.read_bytes())
            linear=(actual_profile.linearize(actual) @ (np.linalg.inv(profile.matrix) @ actual_profile.matrix).T).astype(np.float32)
            exact=bool(np.array_equal(encoded,actual))
            if distance==0 and (not exact or actual_profile.sha256!=profile.sha256):
                raise ValueError("Public lossless gate changed source pixels or profile")
            case["levels"].append({"distance":distance,"encoded_bytes":jxl.stat().st_size,"encoded_sha256":sha256_file(jxl),
                                   "decoded_profile":actual_profile.recipe(),"pixel_exact":exact,
                                   "measurements":measure(reference,linear,profile,recipe)})
            if distance==.05:
                path=args.site/"assets/public-verified"/f"public-{n+1}.png"
                panel(path,reference,linear,profile,recipe)
                case["figure"]=path.relative_to(args.site).as_posix();figures[case["figure"]]=sha256_file(path)
            decoded.unlink();out_icc.unlink()
        records.append(case)
    evidence={"schema":3,"scope":"Six public center crops; source precision retained and declared. Codec edit sensitivity only; no RAW61 comparator or archival-latitude claim",
              "method":"The same five linear-light transformations and ICC-managed measurement recipe as the private rendered-JXL route",
              "recipe_code":{p:sha256_file(ROOT/p) for p in ("scripts/rebuild_public_evidence.py","scripts/run_public_latitude_v2.py","scripts/rebuild_verified_report.py","src/image_color.py","src/report_transforms.py","src/break_even_image_tools.py","src/color_patch_metrics.py")},
              "tools":{tool:sha256_file(args.tools/(tool+".exe")) for tool in ("cjxl","djxl")},
              "versions":{"numpy":np.__version__,"tifffile":tifffile.__version__},
              "records":records,"asset_hashes":figures}
    evidence["evidence_id"]="public-"+fingerprint(evidence)[:16]
    atomic_write_json(args.site/"data/public-evidence.json",evidence)
    return evidence


def main():
    from run_responsive import lower_priority
    lower_priority()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs",type=Path,default=ROOT,help="Checkout root containing public testdata (Git LFS pulled)")
    p.add_argument("--tools",type=Path,required=True)
    p.add_argument("--scratch",type=Path,required=True)
    p.add_argument("--site",type=Path,default=ROOT/"site")
    args=p.parse_args();args.scratch.mkdir(parents=True,exist_ok=True)
    print(build(args)["evidence_id"])
    return 0


if __name__=="__main__":raise SystemExit(main())
