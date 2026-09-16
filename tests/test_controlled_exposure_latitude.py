from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_controlled_exposure_latitude import (  # noqa: E402
    RawFrame,
    exposure_ev,
    green_planes_from_mosaic,
    make_hdr_reference,
    pixel_shift_active,
)


def frame(name: str, exposure: float, ev: float, values: np.ndarray, clipped: np.ndarray) -> RawFrame:
    return RawFrame(
        relative_path=name,
        exposure_seconds=exposure,
        ev=ev,
        iso=100,
        f_number=0.0,
        exposure_compensation=ev,
        sequence_number="1",
        timestamp="",
        focus_mode="Manual",
        pixel_shift_info="n/a",
        green=values.astype(np.float32),
        clipped=clipped,
        near_black=np.zeros_like(clipped),
        clipped_fraction=float(np.mean(clipped)),
        near_black_fraction=0.0,
        clipped_fraction_by_channel={"R": 0.0, "G1": 0.0, "B": 0.0, "G2": 0.0},
        near_black_fraction_by_channel={"R": 0.0, "G1": 0.0, "B": 0.0, "G2": 0.0},
        black_levels=[100, 100, 100, 100],
        white_levels=[1000, 1000, 1000, 1000],
        raw_shape=(values.shape[0] * 2, values.shape[1] * 2),
    )


class ControlledExposureLatitudeTests(unittest.TestCase):
    def test_exposure_ev_uses_shutter_ratio(self) -> None:
        self.assertEqual(exposure_ev(1 / 400, 1 / 50), -3.0)
        self.assertAlmostEqual(exposure_ev(0.3, 1 / 125), math.log2(37.5))

    def test_green_planes_are_black_subtracted_and_channel_normalized(self) -> None:
        raw = np.full((4, 4), 100, dtype=np.uint16)
        raw[0::2, 1::2] = 550
        raw[1::2, 0::2] = 370
        (
            green,
            clipped,
            near_black,
            clipped_fraction,
            near_black_fraction,
            clipped_by_channel,
            black_by_channel,
        ) = (
            green_planes_from_mosaic(
                raw,
                np.array([[0, 1], [3, 2]], dtype=np.uint8),
                b"RGBG",
                [100, 100, 100, 100],
                [1000, 1000, 1000, 1000],
                analysis_stride=1,
                clip_headroom_codes=10,
                black_margin_codes=4,
            )
        )
        expected = (((550 - 100) / 900) + ((370 - 100) / 900)) / 2
        np.testing.assert_allclose(green, expected)
        self.assertFalse(np.any(clipped))
        self.assertFalse(np.any(near_black))
        self.assertEqual(clipped_fraction, 0.0)
        self.assertEqual(near_black_fraction, 0.0)
        self.assertEqual(set(clipped_by_channel), {"R", "G1", "G2", "B"})
        self.assertTrue(all(value == 0.0 for value in clipped_by_channel.values()))
        self.assertGreater(black_by_channel["R"], 0.0)

    def test_hdr_reference_uses_longest_non_clipped_exposure_per_pixel(self) -> None:
        normal_values = np.array([[0.2, 0.4], [0.1, 0.3]], dtype=np.float32)
        long_values = normal_values * 2
        long_clipped = np.array([[False, True], [False, False]])
        normal = frame("normal", 1.0, 0.0, normal_values, np.zeros((2, 2), dtype=bool))
        long = frame("long", 2.0, 1.0, long_values, long_clipped)

        hdr, source_ev = make_hdr_reference([normal, long])

        np.testing.assert_allclose(hdr, normal_values)
        self.assertEqual(source_ev[0, 1], 0.0)
        self.assertEqual(source_ev[0, 0], 1.0)
        self.assertEqual(source_ev[1, 1], 1.0)

        leave_one_out, _ = make_hdr_reference([normal, long], exclude_path="long")
        np.testing.assert_allclose(leave_one_out, normal_values)

    def test_pixel_shift_zero_payload_is_not_a_pixel_shift_capture(self) -> None:
        self.assertFalse(pixel_shift_active("00000000 0 0 0x0"))
        self.assertFalse(pixel_shift_active("n/a"))
        self.assertTrue(pixel_shift_active("17201614 1 4 0x33a"))

    def test_tracked_plan_contains_only_relative_complete_brackets(self) -> None:
        plan = json.loads(
            (ROOT / "metadata/controlled_exposure_latitude_plan.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([case["key"] for case in plan["cases"]], [
            "church",
            "dinner",
            "christmas",
            "white-shirt",
        ])
        self.assertEqual(sum(len(case["files"]) for case in plan["cases"]), 16)
        for case in plan["cases"]:
            self.assertIn(case["normal"], case["files"])
            self.assertEqual(len(case["files"]), len(set(case["files"])))
            for name in case["files"]:
                self.assertFalse(Path(name).is_absolute())
                self.assertNotIn(":", name)

    def test_tracked_result_matches_plan_and_full_bayer_grid(self) -> None:
        plan = json.loads(
            (ROOT / "metadata/controlled_exposure_latitude_plan.json").read_text(
                encoding="utf-8"
            )
        )
        result = json.loads(
            (ROOT / "metadata/controlled_exposure_latitude.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(result["method"]["analysis_stride"], 1)
        self.assertEqual(result["summary"]["case_count"], 4)
        self.assertEqual(result["summary"]["frame_count"], 16)
        self.assertLess(result["summary"]["max_absolute_linearity_error_ev"], 0.2)
        self.assertGreater(result["summary"]["max_all_frames_clipped_fraction"], 0.08)
        planned = {case["key"]: case for case in plan["cases"]}
        for case in result["cases"]:
            expected = planned[case["key"]]
            self.assertEqual(case["normal"], expected["normal"])
            self.assertEqual(
                [frame["file"] for frame in case["frames"]], expected["files"]
            )
            self.assertEqual(case["analysis_grid_shape"], [3188, 4782])
            self.assertTrue(all(frame["iso"] == 100 for frame in case["frames"]))


if __name__ == "__main__":
    unittest.main()
