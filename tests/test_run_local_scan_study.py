from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_local_scan_study as local_study  # noqa: E402


def write_file(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class LocalScanStudyTests(unittest.TestCase):
    def test_slugify_is_stable_for_scan_folder_names(self) -> None:
        self.assertEqual(
            local_study.slugify("Kodak Gold 200-5 1997"),
            "kodak_gold_200_5_1997",
        )

    def test_discover_scan_roots_skips_review_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_file(root / "_review_loose_files" / "scan_manifest.json", "{}")
            write_file(root / "Kodak Gold" / "scan_manifest.json", "{}")

            found = local_study.discover_scan_roots(root, None)

        self.assertEqual([path.name for path in found], ["Kodak Gold"])

    def test_plan_uses_only_dngs_with_all_selected_adc_levels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scan_root = Path(temp_dir) / "Film Set"
            write_file(scan_root / "a.dng")
            write_file(scan_root / "b.dng")
            write_file(scan_root / "c.dng")
            for level in ["lossless", "d003", "d005"]:
                write_file(scan_root / "adc_jxl_dng" / level / "a.dng")
                write_file(scan_root / "adc_jxl_dng" / level / "b.dng")
            write_file(scan_root / "adc_jxl_dng" / "d010" / "a.dng")

            plan = local_study.build_scan_plan(
                scan_root,
                ["lossless", "d003", "d005", "d010"],
                Path(temp_dir) / "results",
            )

        self.assertEqual(plan.verifiable_stems, ["a"])
        self.assertEqual(plan.root_dng_without_selected_candidates, ["c"])
        self.assertEqual(plan.missing_for_candidate_union["d010"], ["b"])

    def test_plan_accepts_nested_source_dngs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scan_root = Path(temp_dir) / "Film Set"
            write_file(scan_root / "dng" / "a.dng")
            for level in ["d020", "d030"]:
                write_file(scan_root / "adc_jxl_dng" / level / "a.dng")

            plan = local_study.build_scan_plan(
                scan_root,
                ["d020", "d030"],
                Path(temp_dir) / "results",
            )

        self.assertEqual(plan.root_dngs, ["a"])
        self.assertEqual(plan.verifiable_stems, ["a"])

    def test_result_complete_requires_patch_and_metadata_diff_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_dir = Path(temp_dir)
            for name in ["SUMMARY.md", "metadata.csv", "summary.csv"]:
                write_file(result_dir / name, "x")

            self.assertFalse(local_study.result_complete(result_dir))

            write_file(result_dir / "patch_summary.csv", "x")

            self.assertFalse(local_study.result_complete(result_dir))

            write_file(result_dir / "metadata_diff.csv", "x")
            write_file(result_dir / "metadata_diff_summary.csv", "x")

            self.assertTrue(local_study.result_complete(result_dir))

    def test_verification_highlights_aggregate_metadata_and_patch_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_dir = Path(temp_dir)
            write_file(
                result_dir / "metadata.csv",
                "\n".join(
                    [
                        "stem,level,source_mib,candidate_mib",
                        "a,d003,100,50",
                        "b,d003,200,80",
                        "a,d005,100,40",
                        "b,d005,200,70",
                    ]
                )
                + "\n",
            )
            write_file(
                result_dir / "patch_summary.csv",
                "\n".join(
                    [
                        "level,transform,median_delta_e00,p95_delta_e00,max_delta_e00,mean_error_rgb_rmse_16bit",
                        "d003,identity,0.01,0.02,0.03,10",
                        "d003,negative_density_hard_print,0.10,0.20,0.30,100",
                        "d005,identity,0.02,0.03,0.04,20",
                        "d005,negative_density_hard_print,0.20,0.30,0.40,200",
                    ]
                )
                + "\n",
            )
            write_file(
                result_dir / "metadata_diff_summary.csv",
                "\n".join(
                    [
                        "level,interpretation,changes,fields",
                        "d003,expected_encoder_change,4,\"bytes, compression_name\"",
                        "d003,review_preservation_change,2,\"active_crop_size, white_level\"",
                        "d005,review_preservation_change,1,white_level",
                    ]
                )
                + "\n",
            )

            highlights = local_study.verification_highlights(result_dir)

        self.assertEqual([row["level"] for row in highlights], ["d003", "d005"])
        self.assertAlmostEqual(highlights[0]["source_gib"], 300 / 1024)
        self.assertAlmostEqual(highlights[0]["candidate_percent"], 130 / 300 * 100)
        self.assertEqual(highlights[1]["hard_max_delta_e00"], 0.40)
        self.assertEqual(highlights[0]["metadata_expected_changes"], 4)
        self.assertEqual(highlights[0]["metadata_review_changes"], 2)
        self.assertEqual(highlights[0]["metadata_review_fields"], "active_crop_size, white_level")


if __name__ == "__main__":
    unittest.main()
