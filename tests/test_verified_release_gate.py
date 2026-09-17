"""Mutation checks against the committed public release; no private inputs."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
import check_verified_release as gate
from incremental_cache import fingerprint


@unittest.skipUnless((ROOT/"site/data/release.json").is_file(),"Complete release has not yet been assembled")
class ReleaseMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release=gate.read(ROOT/"site/data/release.json")

    def reject_release(self,mutate,message):
        changed=copy.deepcopy(self.release);mutate(changed)
        changed["run_id"]="verified-"+fingerprint({k:v for k,v in changed.items() if k not in ("run_id","measurements_csv_sha256")})[:16]
        original=gate.read
        with patch.object(gate,"read",side_effect=lambda p:changed if Path(p).name=="release.json" else original(p)):
            with self.assertRaisesRegex(ValueError,message):gate.check(ROOT/"site",False)

    def test_rejects_a_five_percent_budget_allowance(self):
        def mutate(data):
            row=next(r for r in data["candidates"] if r["cohort"]=="primary_compressed_independent")
            row["encoded_bytes"]=int(row["raw61_bytes"]*1.03)
            row["retained_components"]["jxl_file"]=row["encoded_bytes"]
            row["within_primary_raw61_budget"]=True
        self.reject_release(mutate,"strict size threshold")

    def test_rejects_reclassified_capture_cohort(self):
        def mutate(data):data["candidates"][0]["cohort"]="primary_compressed_independent" if data["candidates"][0]["cohort"]!="primary_compressed_independent" else "diagnostic_flat_field"
        self.reject_release(mutate,"cohort or distance mismatch")

    def test_rejects_changed_transform_recipe(self):
        def mutate(data):next(iter(data["analysis_recipes"].values()))["profile"]="0"*64
        self.reject_release(mutate,"Altered analysis recipe")

    def test_rejects_missing_native_measurement(self):
        def mutate(data):data["candidates"][0]["measurements"].pop()
        self.reject_release(mutate,"measurement scope")

    def test_rejects_different_viewer_profile_even_when_hash_label_is_unchanged(self):
        original=gate.read
        def changed(path):
            data=original(path)
            if Path(path).name=="metadata.json":data["source_profile"]["curves"][0]["parameters"][0]+=1
            return data
        with patch.object(gate,"read",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"reference ICC"):gate.check(ROOT/"site",False)

    def test_rejects_changed_viewer_recipe(self):
        original=gate.read
        def changed(path):
            data=original(path)
            if Path(path).name=="metadata.json":data["browser_transform_recipe"]["undeclared_change"]=True
            return data
        with patch.object(gate,"read",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"transform/registration"):gate.check(ROOT/"site",False)

    def test_rejects_crop_previews_used_as_full_frame_overviews(self):
        original=gate.read
        def changed(path):
            data=original(path)
            if Path(path).name=="metadata.json":data["overviews_by_transform"]=data["images_by_transform"]
            return data
        with patch.object(gate,"read",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"full-frame overview binding"):gate.check(ROOT/"site",False)


if __name__=="__main__":unittest.main()
