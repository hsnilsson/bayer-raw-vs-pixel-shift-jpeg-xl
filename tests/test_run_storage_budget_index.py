from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_storage_budget_index as budget_index  # noqa: E402


def write_file(path: Path, size: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def write_manifest(path: Path) -> None:
    payload = {
        "scan_root_name": "Test Scan",
        "film_stock": "Test Film",
        "film_type": "color negative",
        "shot_year": "1997",
        "capture_sets": [
            {
                "set_id": "a",
                "single_raw": "a.ARW",
                "pixelshift4_dng": "a_ps4.dng",
                "pixelshift16_dng": "a_ps16.dng",
                "storage_budget_role": "primary_candidate",
            },
            {
                "set_id": "b",
                "single_raw": "b.ARW",
                "pixelshift4_dng": None,
                "pixelshift16_dng": None,
                "storage_budget_role": "primary_candidate",
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class StorageBudgetIndexTests(unittest.TestCase):
    def test_collect_rows_compares_candidate_to_single_raw_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scan_root = Path(temp_dir) / "scan"
            write_manifest(scan_root / "scan_manifest.json")
            write_file(scan_root / "a.ARW", 100)
            write_file(scan_root / "a_ps4.dng", 150)
            write_file(scan_root / "a_ps16.dng", 400)
            write_file(scan_root / "adc_jxl_dng" / "d005" / "a_ps16.dng", 98)

            rows = budget_index.collect_rows(scan_root, ["d005"])

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].status, "within_5pct_budget")
        self.assertAlmostEqual(rows[0].candidate_vs_single_raw_pct or 0, 98.0)
        self.assertAlmostEqual(rows[0].candidate_vs_pixelshift16_pct or 0, 24.5)
        self.assertEqual(rows[1].status, "incomplete")
        self.assertIn("missing PixelShift 16 DNG", rows[1].notes)

    def test_row_status_classifies_under_and_over_budget(self) -> None:
        self.assertEqual(
            budget_index.row_status(100, 400, 80, "d005")[0],
            "under_budget",
        )
        self.assertEqual(
            budget_index.row_status(100, 400, 120, "d005")[0],
            "over_budget",
        )


if __name__ == "__main__":
    unittest.main()
