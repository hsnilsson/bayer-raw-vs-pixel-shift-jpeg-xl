from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from color_patch_metrics import delta_e_2000, patch_metric_rows, summarize_patch_metric_rows  # noqa: E402


class DeltaE2000Tests(unittest.TestCase):
    def test_known_sharma_reference_pairs(self) -> None:
        pairs = [
            ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
            ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
            ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
            ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
        ]

        for lab1, lab2, expected in pairs:
            with self.subTest(lab1=lab1, lab2=lab2):
                observed = float(delta_e_2000(np.array(lab1), np.array(lab2)))

                self.assertAlmostEqual(observed, expected, places=4)

    def test_vectorized_delta_e_shape(self) -> None:
        lab1 = np.array([[50.0, 2.6772, -79.7751], [50.0, 2.8361, -74.0200]])
        lab2 = np.array([[50.0, 0.0, -82.7485], [50.0, 0.0, -82.7485]])

        observed = delta_e_2000(lab1, lab2)

        self.assertEqual(observed.shape, (2,))
        self.assertAlmostEqual(float(observed[0]), 2.0425, places=4)
        self.assertAlmostEqual(float(observed[1]), 3.4412, places=4)


class PatchMetricTests(unittest.TestCase):
    def test_equal_patch_mean_can_still_have_pixel_error(self) -> None:
        reference = np.array(
            [
                [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
                [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]],
            ],
            dtype=np.float32,
        )
        candidate = np.full((2, 2, 3), 0.5, dtype=np.float32)

        rows = patch_metric_rows(reference, candidate, patch_size=2)

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["delta_e00"]), 0.0, places=6)
        self.assertGreater(float(rows[0]["error_rgb_rmse_16bit"]), 0.0)
        self.assertGreater(float(rows[0]["ref_luma_std_16bit"]), 0.0)

    def test_channel_bias_is_reported(self) -> None:
        reference = np.full((4, 4, 3), 0.5, dtype=np.float32)
        candidate = reference.copy()
        candidate[:, :, 0] += 0.01

        rows = patch_metric_rows(reference, candidate, patch_size=4)

        self.assertEqual(len(rows), 1)
        self.assertGreater(float(rows[0]["delta_e00"]), 0.0)
        self.assertGreater(float(rows[0]["mean_bias_r_16bit"]), 600.0)
        self.assertAlmostEqual(float(rows[0]["mean_bias_g_16bit"]), 0.0, places=4)
        self.assertAlmostEqual(float(rows[0]["mean_bias_b_16bit"]), 0.0, places=4)

    def test_summary_groups_by_level_and_transform(self) -> None:
        rows = [
            {"level": "d003", "transform": "identity", "delta_e00": 1.0, "mean_abs_bias_16bit": 2.0, "error_rgb_rmse_16bit": 3.0, "mean_bias_r_16bit": 0.0, "mean_bias_g_16bit": 0.0, "mean_bias_b_16bit": 0.0, "error_to_ref_luma_std": 0.5},
            {"level": "d003", "transform": "identity", "delta_e00": 3.0, "mean_abs_bias_16bit": 4.0, "error_rgb_rmse_16bit": 5.0, "mean_bias_r_16bit": 2.0, "mean_bias_g_16bit": 4.0, "mean_bias_b_16bit": 6.0, "error_to_ref_luma_std": 1.5},
        ]

        summary = summarize_patch_metric_rows(rows)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["level"], "d003")
        self.assertEqual(summary[0]["patches"], 2)
        self.assertEqual(summary[0]["median_delta_e00"], 2.0)
        self.assertEqual(summary[0]["mean_abs_bias_16bit"], 3.0)
        self.assertEqual(summary[0]["median_error_to_ref_luma_std"], 1.0)


if __name__ == "__main__":
    unittest.main()
