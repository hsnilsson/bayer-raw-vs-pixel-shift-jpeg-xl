from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import jxl_levels  # noqa: E402


class JxlLevelTests(unittest.TestCase):
    def test_distance_level_maps_to_adc_distance(self) -> None:
        self.assertEqual(jxl_levels.distance_for_level("d003"), "0.03")
        self.assertEqual(jxl_levels.distance_for_level("d010"), "0.10")
        self.assertEqual(jxl_levels.distance_for_level("d020"), "0.20")
        self.assertEqual(jxl_levels.distance_for_level("d050"), "0.50")

    def test_lossless_has_no_distance(self) -> None:
        self.assertIsNone(jxl_levels.distance_for_level("lossless"))

    def test_invalid_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            jxl_levels.require_level("0.20")


if __name__ == "__main__":
    unittest.main()
