"""Create small color-managed PS16 maps of the already approved review crops."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
from PIL import Image,ImageDraw,ImageCms
from break_even_image_tools import read_rgb_image
from image_color import image_profile
from report_transforms import reduce_linear
from rebuild_verified_report import close_image,atomic_bytes,check_resources
from incremental_cache import atomic_write_json,sha256_file,fingerprint


def build(args):
    inventory=json.loads((args.results/"private_inventory.json").read_text(encoding="utf-8"))["frames"]
    records=[];assets={}
    for frame in inventory:
        print("CONTEXT",frame["set_id"],flush=True)
        source=Path(frame["reference"]);profile=image_profile(source)
        pixels=read_rgb_image(source)
        try:
            linear=reduce_linear(pixels,profile,20)
            shape=list(pixels.shape)
        finally:close_image(pixels)
        image=Image.fromarray(np.rint(np.clip(profile.display(linear),0,1)*255).astype(np.uint8))
        draw=ImageDraw.Draw(image)
        for index,crop in enumerate(frame["crops"]):
            x,y,w,h=crop["xywh"]
            bounds=[x/20,y/20,(x+w)/20,(y+h)/20]
            draw.rectangle(bounds,outline="black",width=4);draw.rectangle(bounds,outline="#ffe200",width=2)
            label=crop["name"]
            tx,ty=min(x/20,image.width-85),max(0,y/20-15)
            draw.rectangle([tx,ty,tx+83,ty+14],fill="black")
            draw.text((tx+2,ty+1),label,fill="#ffe200")
        path=args.site/"assets/context-verified"/frame["slug"]/(frame["set_id"]+".png")
        buffer=io.BytesIO();image.save(buffer,format="PNG",icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
        atomic_bytes(path,buffer.getvalue());relative=path.relative_to(args.site).as_posix();assets[relative]=sha256_file(path)
        records.append({"scan_set":frame["scan_set"],"set_id":frame["set_id"],"source_shape":shape,"file":relative,
                        "source_sha256":sha256_file(source),"icc_sha256":profile.sha256,
                        "crops":[{"name":c["name"],"xywh":c["xywh"]} for c in frame["crops"]]})
    payload={"schema":3,"method":"20x20 linear-light box means followed by ICC-managed sRGB display; neutral PS16 location aids only",
             "records":records,"asset_hashes":assets,"script_sha256":sha256_file(Path(__file__)),
             "recipe_code":{p:sha256_file(ROOT/p) for p in ("src/image_color.py","src/report_transforms.py","src/break_even_image_tools.py")}}
    payload["evidence_id"]="contexts-"+fingerprint(payload)[:16]
    atomic_write_json(args.site/"data/context-evidence.json",payload)
    print(payload["evidence_id"])


def main():
    from run_responsive import lower_priority
    lower_priority()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    p.add_argument("--site",type=Path,default=ROOT/"site")
    build(p.parse_args());return 0


if __name__=="__main__":raise SystemExit(main())
