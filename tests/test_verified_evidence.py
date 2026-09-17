from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import numpy as np
import tifffile
from PIL import Image, ImageCms
from audit_dng_evidence import extract
from run_dng_jxl_verification import CropWindow
from rebuild_combiner_evidence import compare
from build_verified_release import candidate_screen
from image_color import SRGB
import finalize_verified_viewers as exporter
from check_verified_release import check_pixel_payload,public_values,safe_path
from incremental_cache import atomic_write_json,sha256_file,fingerprint
from preview_cache import equivalent_png


class VerifiedEvidenceTests(unittest.TestCase):
    def test_export_retries_only_bounded_windows_sharing_locks(self):
        locked=OSError("sharing violation");locked.winerror=32
        calls=[]
        def transient():
            calls.append(1)
            if len(calls)<3:raise locked
            return "complete"
        with patch.object(exporter.time,"sleep") as sleep:
            self.assertEqual(exporter.retry_sharing_violation(transient),"complete")
            self.assertEqual(len(calls),3)
            self.assertEqual(sleep.call_count,2)
        denied=PermissionError("access denied");denied.winerror=5
        with patch.object(exporter.time,"sleep") as sleep:
            with self.assertRaises(PermissionError):exporter.retry_sharing_violation(lambda:(_ for _ in ()).throw(denied))
            sleep.assert_not_called()
        with patch.object(exporter.time,"sleep") as sleep:
            with self.assertRaises(OSError):exporter.retry_sharing_violation(lambda:(_ for _ in ()).throw(locked))
            self.assertEqual(sleep.call_count,4)

    def test_preview_reuse_ignores_only_icc_date_and_rejects_changed_pixels_or_profile(self):
        icc=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        def png(profile=icc,pixel=(20,40,60)):
            buffer=io.BytesIO()
            Image.new("RGB",(3,2),pixel).save(buffer,format="PNG",icc_profile=profile)
            return buffer.getvalue()
        baseline=png()
        dated=bytearray(icc);dated[34:36]=(17).to_bytes(2,"big")
        self.assertTrue(equivalent_png(baseline,png(bytes(dated))))
        changed=bytearray(icc);changed[-1]^=1
        self.assertFalse(equivalent_png(baseline,png(bytes(changed))))
        self.assertFalse(equivalent_png(baseline,png(pixel=(20,40,61))))
        self.assertFalse(equivalent_png(baseline[:-20],baseline))

    def test_public_privacy_gate_accepts_citation_urls_and_rejects_local_paths(self):
        public_values({"source_page":"https://www.loc.gov/item/example/","file":"testdata/source.tif"})
        for value in (r"Q:\private\source.tif","see D:/private/source.tif",r"\\server\private\source.tif","/home/private/source.tif"):
            with self.assertRaisesRegex(ValueError,"Private absolute path"):public_values({"input":value})
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError,"Unsafe public asset path|escaped"):
                safe_path(Path(temporary),"../outside.dat")

    def test_lossless_transport_preserves_every_uint16_code_and_detects_corruption(self):
        raw=np.arange(65536,dtype="<u2").tobytes()
        packed=exporter.pack_pixels(raw)
        self.assertEqual(exporter.unpack_pixels(packed),raw)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"pixels.gz";path.write_bytes(packed)
            asset={"bytes":len(packed),"sha256":sha256_file(path),"decoded_bytes":len(raw),"decoded_sha256":hashlib.sha256(raw).hexdigest()}
            check_pixel_payload(path,asset,len(raw))
            asset["decoded_sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"pixel hash"):
                check_pixel_payload(path,asset,len(raw))

    def test_interrupted_export_commits_journal_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);results=root/"results/run";frame=results/"scan/frame"
            viewer=root/"site/assets/review-viewers/scan/frame/crop";viewer.mkdir(parents=True)
            raw=np.arange(96,dtype="<u2").tobytes();pixels=viewer/"reference.rgb16le";pixels.write_bytes(raw)
            metadata=viewer/"metadata.json"
            atomic_write_json(metadata,{"schema":3,"asset_manifest":{"reference":{"file":pixels.name,"bytes":len(raw),"sha256":sha256_file(pixels)}},
                                        "rgb16":{"sources":{"reference":pixels.name}},"negpy_extreme_inversion":{"legacy":True},
                                        "scan_set":"scan","set_id":"frame","crop_name":"crop","crop":[1,2,8,4],
                                        "browser_transform_recipe":{},"view_modes":[{"key":"identity"}]})
            overview="assets/overviews-verified/scan/frame/crop/reference_identity.webp"
            image=root/"site"/overview;image.parent.mkdir(parents=True)
            Image.new("RGB",(100,60)).save(image)
            atomic_write_json(root/"site/data/overview-evidence.json",{
                "evidence_id":"test-overviews","method":"Synthetic full frame",
                "asset_hashes":{overview:sha256_file(image)},
                "records":[{"scan_set":"scan","set_id":"frame","crop":"crop","crop_xywh":[1,2,8,4],
                            "recipe_sha256":fingerprint({}),"sources":{"reference":{
                                "source_shape":[60,100,3],"source_bounds":[0,0,100,60],"files":{"identity":overview}}}}]})
            atomic_write_json(results/"private_inventory.json",{"frames":[{"slug":"scan","set_id":"frame","crops":[{}]}]})
            atomic_write_json(frame/"complete.json",{"metadata_hashes":{metadata.relative_to(root).as_posix():sha256_file(metadata)}})
            atomic_write_json(frame/"d003.json",{"asset_hashes":{pixels.relative_to(root).as_posix():sha256_file(pixels)}})
            with patch.object(exporter,"ROOT",root):
                with patch.object(exporter,"apply_journal",side_effect=RuntimeError("interrupted")):
                    with self.assertRaisesRegex(RuntimeError,"interrupted"):exporter.finalize(results)
                self.assertTrue((frame/"viewer-export-pending.json").exists())
                exporter.finalize(results)
                first=metadata.read_bytes();exporter.finalize(results)
                self.assertEqual(metadata.read_bytes(),first)
                updated=json.loads(first);self.assertNotIn("negpy_extreme_inversion",updated)
                self.assertFalse(pixels.exists())
                self.assertEqual(exporter.unpack_pixels((viewer/updated["asset_manifest"]["reference"]["file"]).read_bytes()),raw)
                receipt=json.loads((frame/"complete.json").read_text())
                self.assertEqual(receipt["metadata_hashes"][metadata.relative_to(root).as_posix()],sha256_file(metadata))
                for relative,sha in json.loads((frame/"d003.json").read_text())["asset_hashes"].items():
                    self.assertEqual(sha256_file(root/relative),sha)

    def test_dng_tile_selection_respects_active_origin_and_partial_tiles(self):
        array=np.random.default_rng(4).integers(0,65536,(49,67,3),dtype=np.uint16)
        windows=[CropWindow("crosses",10,12,23,19),CropWindow("edge",44,30,17,16)]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/"source.dng"
            tifffile.imwrite(path,array,photometric="rgb",tile=(16,16),
                             extratags=[(50719,"I",2,(3,2),False),(50720,"I",2,(64,47),False)])
            actual=extract(path,windows,Path("unused-decoder"),root)
            for w in windows:
                np.testing.assert_array_equal(actual[w.name],array[w.y+2:w.y+2+w.height,w.x+3:w.x+3+w.width])

    def test_combiner_controls_use_linear_scalar_gain_and_valid_common_support(self):
        rng=np.random.default_rng(19)
        reference=(rng.random((128,128,3),dtype=np.float32)*.4+.1)
        anchor=np.roll(reference*.8,(3,-4),(0,1))
        sony=np.roll(reference*.9,(-2,5),(0,1))
        images,metrics=compare(reference,anchor,sony,SRGB)
        self.assertAlmostEqual(metrics["exposure_match"]["pixelshift2dng"]["gain"],.8,places=6)
        self.assertAlmostEqual(metrics["exposure_match"]["sony_arq"]["gain"],.8/.9,places=6)
        np.testing.assert_allclose(images[0],images[1],atol=1e-7)
        np.testing.assert_allclose(images[0],images[2],atol=1e-7)
        self.assertLess(metrics["range_errors"]["shadow"]["rmse"]["pixelshift2dng"],1e-7)
        self.assertGreater(metrics["detail_correlation"]["sony_arq"],.99999)

    def test_favorable_screens_do_not_hide_an_unaligned_or_failed_crop(self):
        def row(scope,mode,de,hp,applied=True):
            return {"scope":scope,"scope_kind":"native_crop","alignment":{"applied":applied,"valid_fraction":.95},
                    "candidate":{"transform":mode,"delta_e00_p95":de,"structure_loss":hp,"highpass_reference_rms":1},
                    "raw61":{"transform":mode,"delta_e00_p95":1,"structure_loss":1}}
        records=[row("one","identity",.1,.1),row("one","negative_density_hard_print",.1,.1),
                 row("two","identity",.1,1.2),row("two","negative_density_hard_print",2,.1)]
        result=candidate_screen({"measurements":records})
        self.assertTrue(result["alignment_review_pass"])
        self.assertFalse(result["native_color_closer_than_raw61"])
        self.assertFalse(result["native_structure_closer_than_raw61"])
        records[-1]["alignment"]["applied"]=False
        self.assertFalse(candidate_screen({"measurements":records})["alignment_review_pass"])
        empty=[row("flat","identity",0,0),row("flat","negative_density_hard_print",0,0)]
        for record in empty:record["candidate"]["highpass_reference_rms"]=0
        self.assertFalse(candidate_screen({"measurements":empty})["native_structure_closer_than_raw61"])


if __name__=="__main__":unittest.main()
