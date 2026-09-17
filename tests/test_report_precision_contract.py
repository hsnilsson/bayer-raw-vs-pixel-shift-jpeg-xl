from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageCms

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import break_even_image_tools as images
import image_color as color
import incremental_cache as cache
import run_structure_metrics as structure
import run_storage_budget_index as budget


class PrecisionContractTests(unittest.TestCase):
    def test_rgb16_formats_preserve_adjacent_codes(self):
        import imagecodecs
        import tifffile
        pixels = np.array([[[10000, 10001, 65535], [0, 255, 256]]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.png").write_bytes(imagecodecs.png_encode(pixels))
            tifffile.imwrite(root / "sample.tif", pixels, photometric="rgb")
            (root / "sample.ppm").write_bytes(b"P6\n2 1\n65535\n" + pixels.astype(">u2").tobytes())
            for extension in ("png", "tif", "ppm"):
                arr = images.read_rgb_image(root / f"sample.{extension}")
                np.testing.assert_array_equal(arr, pixels)
                self.assertEqual(arr.dtype.itemsize, 2)
                if isinstance(arr, np.memmap):
                    arr._mmap.close()

    def test_constant_field_has_no_false_structure(self):
        for size in (32, 257, 2048):
            field = np.full((size, size), .1, dtype=np.float32)
            result = images.box_blur_luma(field, 2)
            np.testing.assert_allclose(result, field, atol=1e-12, rtol=0)

    def test_blur_matches_direct_neighborhoods(self):
        field = np.random.default_rng(12).random((29, 37))
        padded = np.pad(field, 2, mode="reflect")
        expected = np.lib.stride_tricks.sliding_window_view(padded, (5, 5)).mean(axis=(-1, -2))
        np.testing.assert_allclose(images.box_blur_luma(field, 2), expected, atol=1e-13)

    def test_crop_cannot_silently_shrink(self):
        with self.assertRaisesRegex(ValueError, "bounds"):
            images.crop(np.zeros((10, 10, 3), dtype=np.uint16), "8,8,4,4")

    def test_strict_budget_never_accepts_above_100_percent(self):
        self.assertEqual(budget.row_status(100, 200, 100, "d025")[0], "within_5pct_budget")
        self.assertEqual(budget.row_status(100, 200, 100.001, "d025")[0], "over_budget")

    def test_content_change_with_preserved_size_and_mtime_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metric.json"
            path.write_bytes(b"old!")
            stat = path.stat()
            entry = cache.make_entry("recipe", {"result": path})
            path.write_bytes(b"new!")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertFalse(cache.fresh(entry, "recipe", {"result": path}))

    def test_serial_group_reloads_each_frame_reference(self):
        observed = []
        def analyze(*args, **kw):
            observed.append((float(kw["prepared_reference"][0, 0, 0]), float(kw["prepared_raw61"][0, 0, 0])))
            return None, []
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / str(i) for i in range(6)]
            for p in paths:
                p.touch()
            pixels = {p: np.full((4, 4, 3), i + 1, dtype=np.uint16) for i, p in enumerate(paths)}
            cases = [("set", "frame1", "d025", *paths[:3]), ("set", "frame2", "d025", *paths[3:])]
            with mock.patch.object(structure, "read_rgb_image", side_effect=lambda p: pixels[p]), mock.patch.object(structure, "analyze_case", side_effect=analyze):
                structure.analyze_case_group(cases, None, 2, 2048, "djxl", {})
        self.assertEqual(observed, [(1, 2), (4, 5)])


class ColourContractTests(unittest.TestCase):
    def test_srgb_known_mid_gray_is_linearized(self):
        self.assertAlmostEqual(float(color.srgb_decode(np.array(.5))), .21404114048, places=9)
        values = np.linspace(0, 1, 257)
        np.testing.assert_allclose(color.srgb_encode(color.srgb_decode(values)), values, atol=1e-7)

    def test_parsed_srgb_profile_matches_littlecms(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        parsed = color.profile_from_icc(profile.tobytes())
        source = np.random.default_rng(3).integers(0, 256, (32, 32, 3), dtype=np.uint8)
        oracle = np.asarray(ImageCms.profileToProfile(Image.fromarray(source), profile, profile, outputMode="RGB"))
        actual = np.rint(np.clip(parsed.display(parsed.linearize(source)), 0, 1) * 255)
        np.testing.assert_allclose(actual, oracle, atol=1)

    def test_camera_rgb_does_not_get_an_implicit_display_profile(self):
        with self.assertRaises(ValueError):
            color.profile_from_icc(b"camera-linear without a profile")

    def test_exposure_is_linear_light(self):
        linear = color.SRGB.linearize(np.full((1, 1, 3), .25, dtype=np.float32))
        value = color.SRGB.display(linear * 2)
        expected = color.srgb_encode(color.srgb_decode(np.array(.25)) * 2)
        np.testing.assert_allclose(value, expected, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
