from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageCms

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from image_color import SRGB, RgbProfile, profile_from_icc
from report_transforms import recipe_for, transform, reduce_linear, align_scope, measure, MODES
from break_even_image_tools import unit_luma
import rebuild_verified_report as rebuild
from incremental_cache import sha256_file
from preview_cache import preserve_equivalent_png


class VerifiedColorTests(unittest.TestCase):
    def test_compiled_browser_path_is_identical_to_scalar_oracle(self):
        node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
        if not Path(node).is_file(): self.skipTest("Node runtime unavailable")
        profile = profile_from_icc((ROOT / "tests/fixtures/rtv4_large.icc").read_bytes())
        codes = np.random.default_rng(2).integers(0,65536,(20,23,3),dtype=np.uint16)
        recipe = recipe_for(profile.linearize(codes),profile)
        source = SRGB.recipe(); source["linear_to_reference"] = (np.linalg.inv(profile.matrix) @ SRGB.matrix).tolist()
        payload = {"recipe":recipe,"source":source,"modes":list(MODES),"pixels":codes.reshape(-1,3).tolist()}
        script = "const c=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{let p=JSON.parse(s),max=0;for(const mode of p.modes)for(const ev of [-4,-1,0,1,4]){let fast=c.compileU16(p.recipe,mode,ev,p.source),out=new Float64Array(3);for(const rgb of p.pixels){fast(...rgb,out);let ref=c.display(rgb.map(v=>v/65535),p.recipe,mode,ev,p.source);for(let i=0;i<3;i++)max=Math.max(max,Math.abs(out[i]-ref[i]));}}console.log(max)})"
        result = subprocess.run([node,"-e",script,str(ROOT/"src/report_color.js")],input=json.dumps(payload),text=True,capture_output=True,check=True,timeout=30)
        self.assertLess(float(result.stdout),1e-12)

    def test_actual_working_profile_against_littlecms(self):
        data = (ROOT / "tests/fixtures/rtv4_large.icc").read_bytes()
        profile = profile_from_icc(data)
        pixels = np.random.default_rng(31).integers(0,256,(64,64,3),dtype=np.uint8)
        oracle = np.asarray(ImageCms.profileToProfile(Image.fromarray(pixels),ImageCms.ImageCmsProfile(io.BytesIO(data)),
                ImageCms.createProfile("sRGB"),outputMode="RGB",renderingIntent=1))
        actual = np.rint(np.clip(profile.display(profile.linearize(pixels)),0,1)*255)
        np.testing.assert_allclose(actual,oracle,atol=2,rtol=0)

    def test_browser_agrees_with_float_reference_in_every_mode(self):
        node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
        if not Path(node).is_file(): self.skipTest("Node runtime unavailable")
        profile = profile_from_icc((ROOT / "tests/fixtures/rtv4_large.icc").read_bytes())
        rng = np.random.default_rng(8)
        encoded = rng.random((12,13,3),dtype=np.float32)
        recipe = recipe_for(profile.linearize(encoded),profile)
        # Use a distinct input profile: failing to convert primaries or decode
        # the actual input curve must fail, even if a self-comparison passes.
        source_profile = SRGB.recipe()
        to_reference = np.linalg.inv(profile.matrix) @ SRGB.matrix
        source_profile["linear_to_reference"] = to_reference.tolist()
        commands = []
        expected = []
        for mode in MODES:
            for ev in (-1,0,1):
                linear = ((SRGB.linearize(encoded) @ to_reference.T) * 2**ev).astype(np.float32)
                expected.append(profile.display(transform(linear,mode,recipe)).reshape(-1,3))
                commands.append({"mode":mode,"ev":ev})
        script = "const c=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{let p=JSON.parse(s);console.log(JSON.stringify(p.commands.map(q=>p.pixels.map(v=>c.display(v,p.recipe,q.mode,q.ev,p.profile)))))});"
        payload = {"recipe":recipe,"profile":source_profile,"commands":commands,"pixels":encoded.reshape(-1,3).tolist()}
        result = subprocess.run([node,"-e",script,str(ROOT/"src/report_color.js")],input=json.dumps(payload),text=True,capture_output=True,check=True,timeout=30)
        np.testing.assert_allclose(json.loads(result.stdout),np.array(expected),atol=3e-5,rtol=0)

    def test_box_reduction_averages_linear_light(self):
        pixels = np.tile(np.array([0,65535],dtype=np.uint16)[None,:,None],(6,3,3))
        actual = reduce_linear(pixels,SRGB,2)
        np.testing.assert_allclose(actual,.5,atol=1e-7)
        self.assertGreater(float(SRGB.encode_u16(actual)[0,0,0]),45000)

    def test_profile_inverse_retains_all_integer_codes(self):
        profile = profile_from_icc((ROOT / "tests/fixtures/rtv4_large.icc").read_bytes())
        encoded = np.tile(np.arange(65536,dtype=np.uint16).reshape(256,256,1),(1,1,3))
        actual = profile.encode_u16(profile.linearize(encoded))
        np.testing.assert_array_equal(actual,encoded)

    def test_linear_luminance_does_not_clip_out_of_gamut_values(self):
        array = np.array([[[-.2,1.5,.7]]],dtype=np.float32)
        np.testing.assert_allclose(unit_luma(array),array @ np.array([.2126,.7152,.0722]),atol=1e-7)

    def test_registration_mask_excludes_wrapped_pixels(self):
        ref = np.random.default_rng(5).random((128,128,3),dtype=np.float32)
        raw = np.roll(ref,(7,-5),(0,1))
        aligned, result = align_scope(ref,raw,SRGB)
        self.assertTrue(result["applied"])
        self.assertEqual((result["shift_x_px"],result["shift_y_px"]),(5,-7))
        x,y,w,h = result["valid_xywh"]
        np.testing.assert_array_equal(aligned[y:y+h,x:x+w],ref[y:y+h,x:x+w])
        self.assertLess(result["valid_fraction"],1)

    def test_identity_and_stress_have_zero_loss_for_identical_samples(self):
        linear = np.random.default_rng(4).random((128,128,3),dtype=np.float32)
        for row in measure(linear,linear,SRGB,recipe_for(linear,SRGB)):
            self.assertEqual(row["linear_rmse"],0)
            self.assertEqual(row["delta_e00_p95"],0)
            self.assertEqual(row["structure_loss"],0)

    def test_interrupted_decode_resumes_and_unchanged_run_skips_heavy_stages(self):
        (ROOT / "work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/"work") as directory:
            base = Path(directory)
            pixels = np.random.default_rng(17).integers(0,65536,(128,128,3),dtype=np.uint16)
            icc = (ROOT/"tests/fixtures/rtv4_large.icc").read_bytes()
            profile = profile_from_icc(icc)
            reference = base/"reference.ppm"
            payload = b"P6\n128 128\n65535\n" + pixels.astype(">u2").tobytes()
            reference.write_bytes(payload); reference.with_suffix('.icc').write_bytes(icc)
            candidate = base/"candidate.jxl"; candidate.write_bytes(b"immutable existing encode")
            frame = {"scan_set":"fixture","slug":"fixture","set_id":"frame","cohort":"primary_compressed_independent",
                     "shape":[128,128,3],"reference":str(reference),"source_render":str(reference),
                     "crops":[{"name":"manual-01","xywh":[0,0,128,128]}]}
            for key in ("reference","source_render","raw_render","raw_source","dng_source"):
                frame[key+"_state"] = {"sha256":"source hash"}
            linear = profile.linearize(pixels)
            align = {"valid_xywh":[2,2,124,124]}
            recipe = recipe_for(linear[2:-2,2:-2],profile)
            scope = {"name":"manual-01","kind":"native_crop","factor":1,"input_bounds":[0,0,128,128],
                     "alignment":align,"recipe":recipe,"reference":linear,"raw":linear,
                     "encoded_reference":pixels,"encoded_raw":pixels,"item":{"metadata":str(base/"viewer/metadata.json")},
                     "raw_metrics":measure(linear[2:-2,2:-2],linear[2:-2,2:-2],profile,recipe)}
            audit = {"original":rebuild.state(candidate),"released":rebuild.state(candidate),"metadata_pass":True}
            args = SimpleNamespace(results=base/"results",scratch=base,level=["d025","d030"],tools=base)
            attempts = []
            def decode(command, timeout):
                attempts.append(command)
                if len(attempts) in (1,3): raise RuntimeError("simulated interruption")
                Path(command[2]).write_bytes(payload)
                Path(command[-1].split('=',1)[1]).write_bytes(icc)
            original_profile_bytes = ImageCms.ImageCmsProfile.tobytes
            timestamp = [0]
            def changing_profile_bytes(instance):
                value = bytearray(original_profile_bytes(instance))
                timestamp[0] += 1
                value[34:36] = (timestamp[0] % 60).to_bytes(2,"big")
                return bytes(value)
            with mock.patch.object(rebuild,"check_resources"), mock.patch.object(rebuild,"prepare_scopes",return_value=(profile,[scope])) as prepare, mock.patch.object(rebuild,"prepare_candidate",return_value=(candidate,audit)), mock.patch.object(rebuild,"run",side_effect=decode), mock.patch.object(rebuild,"atomic_bytes",preserve_equivalent_png(rebuild.atomic_bytes)), mock.patch.object(ImageCms.ImageCmsProfile,"tobytes",changing_profile_bytes):
                with self.assertRaisesRegex(RuntimeError,"interruption"):
                    rebuild.process_frame(frame,args,"recipe one")
                checkpoint = args.results/"fixture/frame/d025.json"
                self.assertFalse(checkpoint.exists())
                with self.assertRaisesRegex(RuntimeError,"interruption"):
                    rebuild.process_frame(frame,args,"recipe one")
                self.assertTrue(checkpoint.is_file())
                self.assertFalse(checkpoint.with_name("d030.json").exists())
                completed_hash = sha256_file(checkpoint)
                rebuild.process_frame(frame,args,"recipe one")
                self.assertEqual(sha256_file(checkpoint),completed_hash)
                self.assertEqual(len(attempts),4)
                count = prepare.call_count
                rebuild.process_frame(frame,args,"recipe one")
                self.assertEqual(prepare.call_count,count)
                self.assertEqual(len(attempts),4)
                rebuild.process_frame(frame,args,"changed analysis code")
                self.assertEqual(len(attempts),6)
                self.assertEqual(sha256_file(candidate),audit["original"]["sha256"])


if __name__ == "__main__": unittest.main()
