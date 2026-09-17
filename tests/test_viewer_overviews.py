"""Regression coverage for full-frame backgrounds and independent crop pixels."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from incremental_cache import fingerprint
from viewer_overviews import bind_overviews, overview_record, verify_overview_binding


class OverviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.meta = {"scan_set": "film", "set_id": "frame", "crop_name": "detail",
                     "crop": [130, 170, 20, 30], "browser_transform_recipe": {"identity": True},
                     "asset_manifest": {k: {} for k in ("reference", "raw61", "jxl_d025")},
                     "view_modes": [{"key": k} for k in ("identity", "inverted")],
                     "images_by_transform": {"identity": {"reference": "preview_identity_reference.png"}},
                     "rgb16": {"sources": {"reference": "reference.rgb16le.gz"}}}
        record = {"scan_set": "film", "set_id": "frame", "crop": "detail", "crop_xywh": self.meta["crop"],
                  "recipe_sha256": fingerprint(self.meta["browser_transform_recipe"]), "sources": {}}
        for role in self.meta["asset_manifest"]:
            record["sources"][role] = {"source_shape": [400, 600, 3], "source_bounds": [0, 0, 600, 400],
                                       "files": {mode: f"assets/overviews-verified/film/frame/detail/{role}_{mode}.webp"
                                                 for mode in ("identity", "inverted")}}
        self.evidence = {"records": [record], "evidence_id": "test", "method": "Full-frame test"}
        self.site = ROOT / "site"
        self.path = self.site / "assets/review-viewers/film/frame/detail/metadata.json"

    def test_binds_each_role_and_mode_without_changing_native_pixels(self):
        before = copy.deepcopy(self.meta)
        bind_overviews(self.meta, self.evidence, self.path, self.site)
        verify_overview_binding(self.meta, self.evidence, self.path, self.site)
        for mode, sources in self.meta["overviews_by_transform"].items():
            for role in before["asset_manifest"]:
                actual = (self.path.parent / sources[role]).resolve()
                expected = self.site / self.evidence["records"][0]["sources"][role]["files"][mode]
                self.assertEqual(actual, expected.resolve())
        self.assertEqual(self.meta["rgb16"], before["rgb16"])
        self.assertEqual(self.meta["images_by_transform"], before["images_by_transform"])

    def test_rejects_the_original_crop_as_overview_regression(self):
        bind_overviews(self.meta, self.evidence, self.path, self.site)
        self.meta["overviews_by_transform"] = self.meta["images_by_transform"]
        with self.assertRaisesRegex(ValueError, "full-frame overview binding"):
            verify_overview_binding(self.meta, self.evidence, self.path, self.site)

    def test_rejects_incomplete_coverage_or_stale_recipe(self):
        self.evidence["records"][0]["sources"]["reference"]["source_bounds"] = self.meta["crop"]
        with self.assertRaisesRegex(ValueError, "full frame"):
            overview_record(self.meta, self.evidence)
        self.evidence["records"][0]["recipe_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "tone recipe"):
            overview_record(self.meta, self.evidence)

    def test_rejects_crop_preview_in_evidence_even_with_complete_mapping(self):
        self.evidence["records"][0]["sources"]["reference"]["files"]["identity"] = "assets/review-viewers/film/preview.png"
        with self.assertRaisesRegex(ValueError, "dedicated full-frame"):
            overview_record(self.meta, self.evidence)


class OverviewImageTests(unittest.TestCase):
    def test_linear_reduction_includes_the_last_row_and_column(self):
        import numpy as np
        from image_color import SRGB
        from build_verified_overviews import reduce_full_frame
        pixels = np.arange(9*13*3, dtype=np.uint16).reshape(9, 13, 3) * 171
        pixels[-1, :] = 65535
        pixels[:, -1] = 65535
        actual = reduce_full_frame(pixels, SRGB, max_dim=4)
        linear = SRGB.linearize(pixels)
        xs = [0, 3, 6, 9, 13]; ys = [0, 3, 6, 9]
        expected = np.array([[linear[ys[y]:ys[y+1], xs[x]:xs[x+1]].mean(axis=(0, 1), dtype=np.float64)
                              for x in range(4)] for y in range(3)])
        np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=0)

    def test_raw_crop_marker_uses_source_scale_and_registration(self):
        from build_verified_overviews import crop_on_source
        self.assertEqual(crop_on_source([102, 204, 80, 60], [800, 1200, 3], [400, 600, 3], (2, -4)),
                         [50, 104, 40, 30])


if __name__ == "__main__":
    unittest.main()
