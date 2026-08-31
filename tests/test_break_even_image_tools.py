from __future__ import annotations

import sys
import unittest
import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from break_even_image_tools import shift_rgb, structure_metrics  # noqa: E402


def load_merge_control_module():
    path = ROOT / "scripts" / "run_ied_merge_control.py"
    spec = importlib.util.spec_from_file_location("run_ied_merge_control", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShiftRgbTests(unittest.TestCase):
    def test_zero_shift_preserves_16_bit_samples(self) -> None:
        source = np.array(
            [
                [[0, 1000, 65535], [250, 40000, 512]],
                [[1024, 32768, 65534], [65535, 42, 8192]],
            ],
            dtype=np.uint16,
        )

        shifted = shift_rgb(source, 0.0, 0.0)

        self.assertEqual(shifted.dtype, np.uint16)
        np.testing.assert_array_equal(shifted, source)


class MergeControlRegistrationTests(unittest.TestCase):
    def test_local_registration_refines_to_a_fractional_pixel_shift(self) -> None:
        module = load_merge_control_module()
        rng = np.random.default_rng(42)
        reference = rng.integers(0, 65536, size=(96, 96, 3), dtype=np.uint16)
        candidate = shift_rgb(reference, 2.25, -1.5)
        baseline = structure_metrics(reference, candidate).detail_correlation

        registered, metadata = module.locally_register_crop(reference, candidate)

        self.assertGreater(metadata["selected_detail_correlation"], baseline + 0.5)
        self.assertAlmostEqual(metadata["applied_shift_x_px"], -2.25, places=2)
        self.assertAlmostEqual(metadata["applied_shift_y_px"], 1.5, places=2)
        self.assertEqual(registered.dtype, np.uint16)


if __name__ == "__main__":
    unittest.main()
