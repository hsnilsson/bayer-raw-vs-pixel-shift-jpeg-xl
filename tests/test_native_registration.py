from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from image_color import SRGB
from native_registration import residual_shift, valid_support, registered_raw, provenance, validate_recipe, METHOD
from report_transforms import sample_raw_crop


class NativeRegistrationTests(unittest.TestCase):
    def test_subpixel_translation_with_blur_gain_offset_and_noise(self):
        # Independent Fourier translation of band-limited texture; the RAW-like
        # image has a different PSF, photometry and high-frequency noise.
        rng = np.random.default_rng(812)
        h, w = 256, 320
        fy, fx = np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]
        radius = np.hypot(fy, fx)
        spectrum = np.fft.fft2(rng.normal(size=(h, w))) * np.exp(-(radius/.08)**4)
        ref = np.fft.ifft2(spectrum).real
        for dx, dy in [(.475, -.425), (-.975, -.45), (.5, -.3), (-.45, 1.1)]:
            shifted = np.fft.ifft2(spectrum * np.exp(-2j*np.pi*(fx*dx+fy*dy)) * np.exp(-(radius/.15)**2)).real
            candidate = shifted * 1.3 + .1 + rng.normal(0, .002, (h, w))
            actual = residual_shift(ref, candidate)
            np.testing.assert_allclose(actual, (-dx, -dy), atol=.06, rtol=0)

    def test_rejects_uninformative_and_outside_search_inputs(self):
        flat = np.zeros((128, 128))
        with self.assertRaisesRegex(ValueError, "signal"):
            residual_shift(flat, flat)
        ref = np.random.default_rng(3).normal(size=(128, 128))
        with self.assertRaisesRegex(ValueError, "boundary"):
            residual_shift(ref, np.roll(ref, 3, axis=1))

    def test_fractional_valid_support_conservatively_excludes_edges(self):
        self.assertEqual(valid_support((768, 768, 3), -4.475, -.425), [2, 2, 759, 763])
        self.assertEqual(valid_support((768, 768, 3), -10.975, 3.55), [2, 6, 753, 760])

    def test_raw_samples_original_once_at_combined_shift(self):
        raw = np.random.default_rng(8).integers(1000, 60000, (160, 160, 3), dtype=np.uint16)
        crop, shape, global_shift = (80, 90, 100, 100), (320, 320, 3), (10, -10)
        a = {"method": METHOD, "shift_x_px": -4.475, "shift_y_px": -.425}
        result = registered_raw(raw, SRGB, crop, shape, global_shift, a)
        expected = sample_raw_crop(raw, SRGB, crop, shape, (5.525, -10.425))
        np.testing.assert_array_equal(result, expected)
        # Legacy reconstruction remains byte-for-byte identical on all pixels.
        old = {"applied": True, "shift_x_px": -4, "shift_y_px": 2}
        result = registered_raw(raw, SRGB, crop, shape, global_shift, old)
        expected = np.roll(sample_raw_crop(raw, SRGB, crop, shape, global_shift), (2, -4), (0, 1))
        np.testing.assert_array_equal(result, expected)

    def test_recipe_requires_declared_code_selection_and_residuals(self):
        frame = {"slug": "adox_vlad_resolution_target", "set_id": "_DSC0001-_DSC0016"}
        recipe = {"native_registration": provenance(ROOT), "scopes": [
            {"name": "manual-01", "alignment": {"method": METHOD, "applied": True, "residual_xy_px": [.025, 0]}}]}
        validate_recipe(ROOT, frame, recipe)
        for mutate in [lambda r: r.pop("native_registration"),
                       lambda r: r["native_registration"]["code"].update({"src/native_registration.py": "wrong"}),
                       lambda r: r["scopes"][0]["alignment"].update(residual_xy_px=[.125, 0])]:
            changed = copy.deepcopy(recipe); mutate(changed)
            with self.assertRaises(ValueError):
                validate_recipe(ROOT, frame, changed)
        with self.assertRaisesRegex(ValueError, "recipe"):
            validate_recipe(ROOT, {"slug": "other", "set_id": "other"}, recipe)


if __name__ == "__main__":
    unittest.main()
