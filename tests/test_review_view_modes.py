from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_public_latitude_stress import build_transforms  # noqa: E402


class ReviewViewModesTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
