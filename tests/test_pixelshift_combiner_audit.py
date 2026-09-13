from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_pixelshift_combiner_audit import metric_winner, range_rmse, summarize  # noqa: E402


class PixelshiftCombinerAuditTests(unittest.TestCase):
    def test_range_rmse_uses_only_requested_anchor_band(self) -> None:
        anchor = np.zeros((16, 16), dtype=np.float32)
        anchor[:, 8:] = 0.9
        candidate = anchor.copy()
        candidate[:, :8] = 0.2

        self.assertEqual(range_rmse(anchor, candidate, 0.8, 1.0, blur_radius=0), 0.0)
        self.assertGreater(range_rmse(anchor, candidate, 0.0, 0.1, blur_radius=0), 0.0)

    def test_metric_winner_supports_error_and_correlation_directions(self) -> None:
        self.assertEqual(metric_winner(0.1, 0.2), "pixelshift2dng")
        self.assertEqual(metric_winner(0.1, 0.2, higher_is_better=True), "sony_arq")
        self.assertEqual(metric_winner(0.1, 0.1), "tie")

    def test_summary_keeps_latitude_and_detail_verdicts_separate(self) -> None:
        def crop(highlight: str, shadow: str, detail: str) -> dict[str, object]:
            return {
                "metrics": {
                    "range_errors": {
                        "shadow": {"winner": shadow},
                        "midtone": {"winner": "sony_arq"},
                        "highlight": {"winner": highlight},
                    },
                    "detail_correlation": {"winner": detail},
                    "exposure_match": {
                        "pixelshift2dng_ev": -0.1,
                        "sony_arq_ev": 0.0,
                    },
                }
            }

        result = summarize(
            [
                {
                    "crops": [
                        crop("sony_arq", "sony_arq", "pixelshift2dng"),
                        crop("sony_arq", "sony_arq", "pixelshift2dng"),
                        crop("pixelshift2dng", "sony_arq", "sony_arq"),
                    ]
                }
            ]
        )

        self.assertEqual(result["latitude_reference_winner"], "sony_arq")
        self.assertEqual(result["detail_winner"], "pixelshift2dng")
        self.assertEqual(result["crop_count"], 3)


if __name__ == "__main__":
    unittest.main()
