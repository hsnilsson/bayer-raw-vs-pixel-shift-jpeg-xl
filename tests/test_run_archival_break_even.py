from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_archival_break_even as break_even  # noqa: E402
import run_storage_budget_index as budget_index  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ArchivalBreakEvenTests(unittest.TestCase):
    def test_missing_raw_and_structure_metrics_block_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_dir = root / "verification" / "test_scan_colorpatch"
            write_csv(
                result_dir / "patch_summary.csv",
                [
                    {
                        "level": "d005",
                        "transform": "identity",
                        "p95_delta_e00": "0.01",
                    },
                    {
                        "level": "d005",
                        "transform": "negative_density_hard_print",
                        "p95_delta_e00": "0.04",
                        "mean_bias_r_16bit": "1",
                        "mean_bias_g_16bit": "-2",
                        "mean_bias_b_16bit": "3",
                    },
                ],
            )
            write_csv(
                result_dir / "metadata_diff_summary.csv",
                [
                    {
                        "level": "d005",
                        "interpretation": "expected_encoder_change",
                        "changes": "1",
                        "fields": "compression",
                    }
                ],
            )
            budget_rows = [
                budget_index.BudgetRow(
                    scan_set="Test Scan",
                    film_stock="Test Film",
                    film_type="color negative",
                    shot_year="1997",
                    set_id="frame001",
                    single_raw="single.ARW",
                    pixelshift4_dng="",
                    pixelshift16_dng="ps16.dng",
                    level="d005",
                    single_raw_mib=100.0,
                    pixelshift4_mib=None,
                    pixelshift16_mib=400.0,
                    candidate_mib=98.0,
                    candidate_vs_single_raw_pct=98.0,
                    candidate_vs_pixelshift16_pct=24.5,
                    storage_budget_role="primary_candidate",
                    status="within_5pct_budget",
                    notes="candidate size is within +/-5% of single-shot raw",
                )
            ]

            rows = break_even.build_rows(budget_rows, root / "verification", {}, {})

        self.assertEqual(rows[0].color_verdict, "blocked_missing_raw61_color_metrics")
        self.assertIn("raw61_loss_metrics", rows[0].evidence_status)
        self.assertIn("structure_metrics", rows[0].evidence_status)
        self.assertEqual(rows[0].verdict, rows[0].evidence_status)

    def test_complete_evidence_can_produce_ps16_likely_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_dir = root / "verification" / "test_scan_colorpatch"
            write_csv(
                result_dir / "patch_summary.csv",
                [
                    {
                        "level": "d005",
                        "transform": "identity",
                        "p95_delta_e00": "0.01",
                    },
                    {
                        "level": "d005",
                        "transform": "negative_density_hard_print",
                        "p95_delta_e00": "0.04",
                        "mean_bias_r_16bit": "1",
                        "mean_bias_g_16bit": "-2",
                        "mean_bias_b_16bit": "3",
                    },
                ],
            )
            write_csv(
                result_dir / "metadata_diff_summary.csv",
                [
                    {
                        "level": "d005",
                        "interpretation": "expected_encoder_change",
                        "changes": "1",
                        "fields": "compression",
                    }
                ],
            )
            budget_rows = [
                budget_index.BudgetRow(
                    scan_set="Test Scan",
                    film_stock="Test Film",
                    film_type="color negative",
                    shot_year="1997",
                    set_id="frame001",
                    single_raw="single.ARW",
                    pixelshift4_dng="",
                    pixelshift16_dng="ps16.dng",
                    level="d005",
                    single_raw_mib=100.0,
                    pixelshift4_mib=None,
                    pixelshift16_mib=400.0,
                    candidate_mib=98.0,
                    candidate_vs_single_raw_pct=98.0,
                    candidate_vs_pixelshift16_pct=24.5,
                    storage_budget_role="primary_candidate",
                    status="within_5pct_budget",
                    notes="candidate size is within +/-5% of single-shot raw",
                )
            ]
            raw = {
                ("Test Scan", "frame001"): break_even.RawLossRow(
                    scan_set="Test Scan",
                    set_id="frame001",
                    raw61_color_delta_e00_p95_identity=0.2,
                    raw61_color_delta_e00_p95_stress=0.1,
                    raw61_channel_bias_max_stress=5,
                    raw61_clipping_delta_stress=0,
                    raw61_structure_loss=0.5,
                    notes="",
                )
            }
            structure = {
                ("Test Scan", "frame001", "d005"): break_even.StructureRow(
                    scan_set="Test Scan",
                    set_id="frame001",
                    level="d005",
                    scope="native-detail",
                    raw61_structure_loss=0.5,
                    jxl_structure_loss=0.2,
                    artifact_risk="low",
                    structure_verdict="ps16_jxl_likely_wins",
                    notes="",
                )
            }

            rows = break_even.build_rows(budget_rows, root / "verification", raw, structure)

        self.assertEqual(rows[0].evidence_status, "complete")
        self.assertEqual(rows[0].color_verdict, "ps16_jxl_wins")
        self.assertEqual(rows[0].verdict, "ps16_jxl_likely_wins")

    def test_metadata_review_changes_block_sole_master_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_dir = root / "verification" / "test_scan_colorpatch"
            write_csv(
                result_dir / "patch_summary.csv",
                [
                    {
                        "level": "d005",
                        "transform": "negative_density_hard_print",
                        "p95_delta_e00": "0.04",
                    }
                ],
            )
            write_csv(
                result_dir / "metadata_diff_summary.csv",
                [
                    {
                        "level": "d005",
                        "interpretation": "review_preservation_change",
                        "changes": "2",
                        "fields": "white_level, opcode_list2",
                    }
                ],
            )
            budget_rows = [
                budget_index.BudgetRow(
                    scan_set="Test Scan",
                    film_stock="Test Film",
                    film_type="color negative",
                    shot_year="1997",
                    set_id="frame001",
                    single_raw="single.ARW",
                    pixelshift4_dng="",
                    pixelshift16_dng="ps16.dng",
                    level="d005",
                    single_raw_mib=100.0,
                    pixelshift4_mib=None,
                    pixelshift16_mib=400.0,
                    candidate_mib=98.0,
                    candidate_vs_single_raw_pct=98.0,
                    candidate_vs_pixelshift16_pct=24.5,
                    storage_budget_role="primary_candidate",
                    status="within_5pct_budget",
                    notes="",
                )
            ]
            raw = {
                ("Test Scan", "frame001"): break_even.RawLossRow(
                    "Test Scan", "frame001", 0.2, 0.1, 5, 0, 0.5, ""
                )
            }
            structure = {
                ("Test Scan", "frame001", "d005"): break_even.StructureRow(
                    "Test Scan",
                    "frame001",
                    "d005",
                    "native-detail",
                    0.5,
                    0.2,
                    "low",
                    "ps16_jxl_likely_wins",
                    "",
                )
            }

            rows = break_even.build_rows(budget_rows, root / "verification", raw, structure)

        self.assertEqual(rows[0].metadata_risk, "review_required")
        self.assertEqual(rows[0].evidence_status, "blocked_operational_review")
        self.assertEqual(rows[0].verdict, "blocked_operational_review")

    def test_blocked_structure_row_keeps_verdict_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_dir = root / "verification" / "test_scan_colorpatch"
            write_csv(
                result_dir / "patch_summary.csv",
                [
                    {
                        "level": "lossless",
                        "transform": "negative_density_hard_print",
                        "p95_delta_e00": "0.0",
                    }
                ],
            )
            write_csv(
                result_dir / "metadata_diff_summary.csv",
                [
                    {
                        "level": "lossless",
                        "interpretation": "expected_encoder_change",
                        "changes": "1",
                        "fields": "compression",
                    }
                ],
            )
            budget_rows = [
                budget_index.BudgetRow(
                    scan_set="Test Scan",
                    film_stock="Test Film",
                    film_type="color negative",
                    shot_year="1997",
                    set_id="frame001",
                    single_raw="single.ARW",
                    pixelshift4_dng="",
                    pixelshift16_dng="ps16.dng",
                    level="lossless",
                    single_raw_mib=100.0,
                    pixelshift4_mib=None,
                    pixelshift16_mib=400.0,
                    candidate_mib=98.0,
                    candidate_vs_single_raw_pct=98.0,
                    candidate_vs_pixelshift16_pct=24.5,
                    storage_budget_role="primary_candidate",
                    status="within_5pct_budget",
                    notes="",
                )
            ]
            raw = {
                ("Test Scan", "frame001"): break_even.RawLossRow(
                    "Test Scan", "frame001", 0.2, 0.1, 5, 0, 0.5, ""
                )
            }
            structure = {
                ("Test Scan", "frame001", "lossless"): break_even.StructureRow(
                    "Test Scan",
                    "frame001",
                    "lossless",
                    "full",
                    None,
                    None,
                    "unknown",
                    "blocked_missing_structure_inputs",
                    "missing JXL candidate render",
                )
            }

            rows = break_even.build_rows(budget_rows, root / "verification", raw, structure)

        self.assertEqual(rows[0].evidence_status, "blocked_missing_structure_metrics")
        self.assertEqual(rows[0].verdict, "blocked_missing_structure_metrics")


if __name__ == "__main__":
    unittest.main()
