from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from break_even_image_tools import shift_rgb  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
