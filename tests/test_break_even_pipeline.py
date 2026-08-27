from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from break_even_image_tools import (  # noqa: E402
    phase_correlation_shift,
    register_candidate_to_reference,
    structure_metrics,
    write_rgb_tiff,
)
import run_raw61_loss_metrics as raw61_loss  # noqa: E402
import run_structure_metrics as structure_runner  # noqa: E402
import make_break_even_review_panels as review_panels  # noqa: E402
import generate_break_even_report_site as report_site  # noqa: E402


def write_png(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8)).save(path)


def textured_rgb(height: int = 96, width: int = 128) -> np.ndarray:
    y, x = np.mgrid[:height, :width]
    base = (
        90
        + 40 * np.sin(x / 5.0)
        + 30 * np.cos(y / 7.0)
        + ((x * 13 + y * 17) % 23)
    )
    arr = np.stack(
        [
            np.clip(base + 20, 0, 255),
            np.clip(base, 0, 255),
            np.clip(base - 15, 0, 255),
        ],
        axis=2,
    )
    arr[28:42, 55:80, :] = [220, 180, 130]
    return arr.astype(np.uint8)


class BreakEvenPipelineTests(unittest.TestCase):
    def test_phase_correlation_returns_alignment_shift(self) -> None:
        reference = np.zeros((64, 64), dtype=np.float32)
        reference[20:30, 25:35] = 1.0
        candidate = np.roll(np.roll(reference, 5, axis=0), -7, axis=1)

        shift_x, shift_y, _peak, confidence = phase_correlation_shift(reference, candidate)

        self.assertEqual(round(shift_x), 7)
        self.assertEqual(round(shift_y), -5)
        self.assertGreater(confidence, 100.0)

    def test_register_candidate_to_reference_scales_and_aligns(self) -> None:
        reference = textured_rgb(96, 128)
        shifted = np.roll(np.roll(reference, 3, axis=0), -4, axis=1)
        candidate = shifted[::2, ::2, :]

        registered, result = register_candidate_to_reference(reference, candidate, max_preview_dim=256)

        self.assertEqual(registered.shape, reference.shape)
        self.assertAlmostEqual(result.scale_x, 2.0)
        self.assertAlmostEqual(result.scale_y, 2.0)
        self.assertGreater(result.overlap_fraction, 0.90)

    def test_raw61_loss_metrics_writes_break_even_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = textured_rgb()
            candidate = np.clip(reference.astype(np.int16) - 3, 0, 255).astype(np.uint8)
            ref_path = root / "ps16.png"
            cand_path = root / "raw61.png"
            write_png(ref_path, reference)
            write_png(cand_path, candidate)

            row = raw61_loss.analyze_pair(
                "Synthetic Scan",
                "frame001",
                ref_path,
                cand_path,
                root / "results",
                patch_size=32,
                rgb_space="srgb",
                crop_spec=None,
                max_analysis_dim=0,
            )

            self.assertEqual(row.scan_set, "Synthetic Scan")
            self.assertIsNotNone(row.raw61_color_delta_e00_p95_identity)
            self.assertIsNotNone(row.raw61_color_delta_e00_p95_stress)
            self.assertIsNotNone(row.raw61_channel_bias_max_stress)

    def test_structure_metrics_prefers_closer_jxl_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = textured_rgb()
            raw61 = np.asarray(
                Image.fromarray(reference).resize((64, 48), Image.Resampling.BICUBIC).resize(
                    (128, 96), Image.Resampling.BICUBIC
                )
            )
            jxl = np.clip(reference.astype(np.int16) + 1, 0, 255).astype(np.uint8)
            ref_path = root / "ps16.png"
            raw_path = root / "raw61.png"
            jxl_path = root / "jxl.png"
            write_png(ref_path, reference)
            write_png(raw_path, raw61)
            write_png(jxl_path, jxl)

            row, details = structure_runner.analyze_case(
                "Synthetic Scan",
                "frame001",
                "d005",
                ref_path,
                raw_path,
                jxl_path,
                crop_spec=None,
                highpass_radius=2,
                max_analysis_dim=0,
            )

            self.assertEqual(row.structure_verdict, "ps16_jxl_likely_wins")
            self.assertEqual(len(details), 2)
            self.assertLess(float(row.jxl_structure_loss), float(row.raw61_structure_loss))

    def test_structure_loss_is_zero_for_identical_images(self) -> None:
        arr = textured_rgb()
        metrics = structure_metrics(arr, arr, radius=2)
        self.assertEqual(metrics.structure_loss, 0.0)
        self.assertAlmostEqual(metrics.detail_correlation, 1.0)

    def test_structure_metrics_can_reuse_cached_jxl_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = textured_rgb()
            raw61 = np.asarray(
                Image.fromarray(reference).resize((32, 24), Image.Resampling.BICUBIC).resize(
                    (128, 96), Image.Resampling.BICUBIC
                )
            )
            ref_path = root / "ps16.png"
            raw_path = root / "raw61.png"
            write_png(ref_path, reference)
            write_png(raw_path, raw61)
            cached = structure_runner.StructureDetailRow(
                scan_set="Synthetic Scan",
                set_id="frame001",
                level="d030",
                scope="full",
                candidate_role="ps16_jxl_candidate",
                highpass_rmse=0.001,
                highpass_reference_rms=0.1,
                structure_loss=0.01,
                detail_correlation=0.99,
                detail_energy_ratio=1.0,
            )

            row, details = structure_runner.analyze_case(
                "Synthetic Scan",
                "frame001",
                "d030",
                ref_path,
                raw_path,
                root / "missing.jxl",
                crop_spec=None,
                highpass_radius=2,
                max_analysis_dim=0,
                cached_jxl_detail=cached,
            )

            self.assertEqual(row.structure_verdict, "ps16_jxl_likely_wins")
            self.assertIn("reused_jxl_detail=true", row.notes)
            self.assertEqual(details[1], cached)

    def test_review_panel_local_alignment_corrects_crop_shift(self) -> None:
        reference = textured_rgb()
        shifted = np.roll(np.roll(reference, 2, axis=0), -3, axis=1)

        aligned, result = review_panels.local_align_raw61(reference, shifted, max_shift=8)

        self.assertTrue(result.applied)
        self.assertAlmostEqual(result.shift_x_px, 3.0)
        self.assertAlmostEqual(result.shift_y_px, -2.0)
        self.assertLess(np.mean(np.abs(aligned.astype(np.int16) - reference.astype(np.int16))), 6.0)

    def test_report_site_classifies_size_and_delta_e(self) -> None:
        self.assertEqual(report_site.classify_size(95.0), "good")
        self.assertEqual(report_site.classify_size(108.0), "warn")
        self.assertEqual(report_site.classify_size(130.0), "bad")
        self.assertEqual(report_site.classify_delta_e(0.8), "good")
        self.assertEqual(report_site.classify_delta_e(1.7), "warn")
        self.assertEqual(report_site.classify_delta_e(2.7), "risk")
        self.assertEqual(report_site.classify_delta_e(3.5), "bad")

    def test_report_site_marks_under_budget_warn_color_as_promising(self) -> None:
        summary = report_site.LevelSummary(
            level="d030",
            rows=3,
            median_size_pct=80.0,
            min_size_pct=70.0,
            max_size_pct=90.0,
            max_jxl_delta_e=1.7,
            median_raw_delta_e=5.0,
            max_jxl_structure_loss=0.2,
            median_raw_structure_loss=1.0,
            verdicts={"ps16_jxl_likely_wins": 3},
            status="",
        )

        self.assertEqual(report_site.status_for(summary), "Promising")

    def test_uint8_tiff_fallback_can_write_without_tifffile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tiny.tif"
            write_rgb_tiff(path, textured_rgb(16, 16))
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
