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

    def test_build_summary_records_adobe_requirement(self) -> None:
        result = qualification.build_summary([{"qualification": "pass"}], [], 200.0, adobe_required=True)
        self.assertTrue(result["gates"]["adobe_dng_converter_acceptance_required"])

    def test_encode_fingerprint_tracks_encoder_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.dng"
            raw = Path(temp_dir) / "raw.arw"
            source.write_bytes(b"dng")
            raw.write_bytes(b"raw")
            case = qualification.QualificationCase("film", "frame", source, raw, "film|frame")
            fingerprint = qualification.encode_fingerprint(case, 0.01, 7, 8, "wrapper:abc")
        self.assertEqual("wrapper:abc", fingerprint["encoder_signature"])

    def test_load_raw61_baselines_uses_one_repeated_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = Path(temp_dir) / "matrix.csv"
            matrix.write_text(
                "scan_set,set_id,raw61_color_delta_e00_p95_stress,raw61_structure_loss\n"
                "film,frame,4.5,1.2\nfilm,frame,4.5,1.2\n",
                encoding="utf-8",
            )
            result = qualification.load_raw61_baselines(matrix)
        self.assertEqual({"stress_p95_delta_e00": 4.5, "structure_loss": 1.2}, result[("film", "frame")])

    def test_public_summary_omits_private_paths_and_commands(self) -> None:
        result = {
            "generated_at_utc": "now",
            "gates": {"maximum_candidate_mib": 200},
            "records": [{
                "scan_set": "film", "set_id": "frame", "qualification": "pass", "reasons": [], "warnings": [],
                "encode": {"status": "encoded", "candidate_mib": 100, "candidate_pct_raw61": 90, "candidate_sha256": "abc", "source_dng": "private"},
                "verification": {"status": "verified", "identity_p95_delta_e00": 0.01, "stress_p95_delta_e00": 0.5, "worst_structure_loss": 0.2, "preservation_review_changes": 0},
                "full_segment_decode": {"status": "decoded", "segments": 2},
                "adobe_dng_converter": {"status": "accepted", "command": ["private"]},
                "raw61_comparison": {"candidate_to_raw61_stress_color_ratio": 0.5},
            }],
        }
        public = qualification.build_public_summary(result)
        serialized = json.dumps(public)
        self.assertNotIn("private", serialized)
        self.assertEqual(1, public["summary"]["technical_master_passed"])


if __name__ == "__main__":
    unittest.main()
