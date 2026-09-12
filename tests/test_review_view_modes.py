from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_public_latitude_stress import build_transforms, estimate_linear_exposure_gain  # noqa: E402


class ReviewViewModesTests(unittest.TestCase):
    def test_big_endian_16bit_input_keeps_its_full_sample_range(self) -> None:
        reference = np.array([[[0, 32768, 65535]]], dtype=">u2")

        identity = build_transforms(reference)[0].apply(reference)

        self.assertTrue(np.allclose(identity, [[[0.0, 32768 / 65535, 1.0]]]))

    def test_extreme_edit_modes_are_available_and_preserve_array_shape(self) -> None:
        gradient = np.linspace(0, 65535, 48, dtype=np.uint16)
        reference = np.stack(
            [
                np.tile(gradient, (32, 1)),
                np.tile(np.roll(gradient, 5), (32, 1)),
                np.tile(np.roll(gradient, 11), (32, 1)),
            ],
            axis=2,
        )
        transforms = {transform.name: transform for transform in build_transforms(reference)}

        for name in [
            "identity",
            "shadow_recovery_luma_p12",
            "highlight_separation_luma_p88_p998",
            "negative_density_hard_print",
            "negative_density_hard_shadow_recovery",
        ]:
            result = transforms[name].apply(reference)
            self.assertEqual(result.shape, reference.shape)
            self.assertTrue(np.isfinite(result).all())
            self.assertGreaterEqual(float(result.min()), 0.0)
            self.assertLessEqual(float(result.max()), 1.0)

        self.assertEqual(transforms["shadow_recovery_luma_p12"].label, "Shadow recovery")
        self.assertEqual(transforms["highlight_separation_luma_p88_p998"].label, "Highlight separation")
        self.assertEqual(
            transforms["negative_density_hard_shadow_recovery"].label,
            "Hard inversion + shadow recovery",
        )

    def test_luminance_modes_are_grayscale(self) -> None:
        reference = np.zeros((24, 32, 3), dtype=np.uint16)
        reference[:, :, 0] = np.linspace(5000, 65535, 32, dtype=np.uint16)
        reference[:, :, 1] = np.linspace(1000, 50000, 32, dtype=np.uint16)
        reference[:, :, 2] = np.linspace(15000, 30000, 32, dtype=np.uint16)
        transforms = {transform.name: transform for transform in build_transforms(reference)}

        for name in ["shadow_recovery_luma_p12", "highlight_separation_luma_p88_p998"]:
            result = transforms[name].apply(reference)
            self.assertTrue(np.array_equal(result[:, :, 0], result[:, :, 1]))
            self.assertTrue(np.array_equal(result[:, :, 1], result[:, :, 2]))
            self.assertIsNotNone(transforms[name].apply_with_linear_gain)

    def test_exposure_gain_recovers_global_linear_level_difference(self) -> None:
        encoded = np.linspace(0.15, 0.85, 64, dtype=np.float32)
        reference_unit = np.repeat(encoded[None, :, None], 3, axis=2)
        reference_unit = np.repeat(reference_unit, 16, axis=0)
        reference = np.round(reference_unit * 65535).astype(np.uint16)
        candidate_linear = np.power(reference_unit, 2.2) * 0.5
        candidate = np.round(np.power(candidate_linear, 1 / 2.2) * 65535).astype(np.uint16)

        gain = estimate_linear_exposure_gain(reference, candidate)

        self.assertAlmostEqual(gain, 2.0, places=3)
        transforms = {transform.name: transform for transform in build_transforms(reference)}
        for name in ["shadow_recovery_luma_p12", "highlight_separation_luma_p88_p998"]:
            transform = transforms[name]
            assert transform.apply_with_linear_gain is not None
            self.assertTrue(
                np.allclose(
                    transform.apply(reference),
                    transform.apply_with_linear_gain(candidate, gain),
                    atol=2e-4,
                )
            )

    def test_exposure_gain_is_one_when_no_valid_midtones_exist(self) -> None:
        black = np.zeros((8, 8, 3), dtype=np.uint16)

        self.assertEqual(estimate_linear_exposure_gain(black, black), 1.0)


if __name__ == "__main__":
    unittest.main()
