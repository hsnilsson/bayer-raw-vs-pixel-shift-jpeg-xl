from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_muimg_archive_qualification as qualification  # noqa: E402


class MuimgArchiveQualificationTests(unittest.TestCase):
    def test_discover_cases_rejects_unpaired_and_stale_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan = root / "film"
            scan.mkdir()
            (scan / "good.dng").write_bytes(b"dng")
            (scan / "raw.arw").write_bytes(b"raw")
            manifest = {
                "scan_root_name": "film",
                "capture_sets": [
                    {
                        "set_id": "frame",
                        "single_raw": "raw.arw",
                        "pixelshift16_dng": "good.dng",
                        "storage_budget_role": "primary_candidate",
                    },
                    {
                        "set_id": "stale",
                        "single_raw": "raw.arw",
                        "pixelshift16_dng": "missing.dng",
                        "storage_budget_role": "primary_candidate",
                    },
                    {
                        "set_id": "unpaired",
                        "single_raw": None,
                        "pixelshift16_dng": "good.dng",
                        "storage_budget_role": "unpaired_secondary",
                    },
                ],
            }
            (scan / "scan_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            crop_plan = root / "crops.json"
            crop_plan.write_text(json.dumps({"cases": {"film|frame": {}}}), encoding="utf-8")

            cases, skipped = qualification.discover_cases(root, crop_plan)

            self.assertEqual(["film|frame"], [case.crop_case for case in cases])
            self.assertEqual(2, len(skipped))

    def test_build_summary_fails_when_any_case_fails(self) -> None:
        result = qualification.build_summary(
            [{"qualification": "pass"}, {"qualification": "fail"}],
            [],
            200.0,
        )
        self.assertEqual("fail", result["decision"])
        self.assertEqual({"cases": 2, "passed": 1, "failed": 1, "skipped_manifest_entries": 0}, result["summary"])


if __name__ == "__main__":
    unittest.main()
