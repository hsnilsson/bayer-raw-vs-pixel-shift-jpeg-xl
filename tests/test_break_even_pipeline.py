from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from break_even_image_tools import (  # noqa: E402
    phase_correlation_shift,
    register_candidate_to_reference,
    structure_metrics,
    write_rgb_tiff,
)
from incremental_cache import fingerprint, fresh, make_entry  # noqa: E402
import run_raw61_loss_metrics as raw61_loss  # noqa: E402
import run_structure_metrics as structure_runner  # noqa: E402
import make_break_even_review_panels as review_panels  # noqa: E402
import make_break_even_context_images as context_images  # noqa: E402
import make_break_even_review_viewers as review_viewers  # noqa: E402
import generate_break_even_report_site as report_site  # noqa: E402
import run_rendered_ps16_jxl_matrix as rendered_matrix  # noqa: E402
import read_crop_selection_guides as crop_guides  # noqa: E402


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
    def test_incremental_cache_invalidates_changed_input_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.bin"
            output = root / "derived.bin"
            source.write_bytes(b"source-v1")
            output.write_bytes(b"derived-v1")
            expected = fingerprint({"source": source.stat().st_mtime_ns, "parameter": "v1"})
            entry = make_entry(expected, {"output": output}, root)

            self.assertTrue(fresh(entry, expected, {"output": output}, root))
            output.write_bytes(b"derived-v2-with-change")
            self.assertFalse(fresh(entry, expected, {"output": output}, root))

            entry = make_entry(expected, {"output": output}, root)
            changed = fingerprint({"source": source.stat().st_mtime_ns, "parameter": "v2"})
            self.assertFalse(fresh(entry, changed, {"output": output}, root))

    def test_viewer_build_inputs_change_when_a_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ps16 = root / "ps16.tif"
            raw61 = root / "raw61_registered_to_ps16.tif"
            jxl_root = root / "jxl"
            jxl = jxl_root / "scan" / "frame" / "d030" / "ps16.jxl"
            for path, contents in [(ps16, b"ps16"), (raw61, b"raw61"), (jxl, b"jxl")]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)

            original = review_viewers.viewer_build_inputs(
                ps16,
                raw61,
                jxl_root,
                "scan",
                "frame",
                ["d030"],
                ["identity"],
                (1, 2, 3, 4),
                1024,
                360,
                32.0,
            )
            raw61.write_bytes(b"raw61-updated")
            updated = review_viewers.viewer_build_inputs(
                ps16,
                raw61,
                jxl_root,
                "scan",
                "frame",
                ["d030"],
                ["identity"],
                (1, 2, 3, 4),
                1024,
                360,
                32.0,
            )

            self.assertNotEqual(fingerprint(original), fingerprint(updated))
            self.assertFalse(review_viewers.viewer_metadata_is_current({}, original))
            self.assertTrue(
                review_viewers.viewer_metadata_is_current(
                    {"build_fingerprint": fingerprint(updated)}, updated
                )
            )

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

    def test_structure_metrics_group_resizes_uncached_jxl_like_prepared_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = textured_rgb(96, 128)
            raw61 = np.clip(reference.astype(np.int16) - 2, 0, 255).astype(np.uint8)
            jxl = np.clip(reference.astype(np.int16) + 1, 0, 255).astype(np.uint8)
            ref_path = root / "ps16.png"
            raw_path = root / "raw61.png"
            jxl_path = root / "jxl.png"
            write_png(ref_path, reference)
            write_png(raw_path, raw61)
            write_png(jxl_path, jxl)

            rows, details = structure_runner.analyze_case_group(
                [("Synthetic Scan", "frame001", "d100", ref_path, raw_path, jxl_path)],
                crop_spec=None,
                highpass_radius=2,
                max_analysis_dim=64,
                djxl="",
                reusable_jxl={},
            )

            self.assertIn(rows[0].structure_verdict, {"ps16_jxl_likely_wins", "uncertain"})
            self.assertIsNotNone(rows[0].jxl_structure_loss)
            self.assertEqual(len(details), 2)
            self.assertIn("analysis_scale=", rows[0].notes)

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

    def test_context_crop_parser_accepts_valid_crop(self) -> None:
        self.assertEqual(context_images.parse_crop("10,20,30,40"), (10, 20, 30, 40))

    def test_context_images_reads_crop_plan_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "crop_plan.json"
            path.write_text(
                """{
                  "cases": {
                    "film|frame": {
                      "scan_set": "Film",
                      "set_id": "frame",
                      "crops": [
                        {"name": "manual-01", "crop": [10, 20, 30, 40]},
                        {"name": "manual-02", "crop": [50, 60, 70, 80]}
                      ]
                    }
                  }
                }""",
                encoding="utf-8",
            )

            jobs = context_images.read_crop_plan(path)

            self.assertEqual(
                jobs,
                [
                    (context_images.ContextCase("Film", "frame"), "manual-01", (10, 20, 30, 40)),
                    (context_images.ContextCase("Film", "frame"), "manual-02", (50, 60, 70, 80)),
                ],
            )

    def test_review_viewers_reads_crop_plan_and_default_levels_include_hard_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "crop_plan.json"
            path.write_text(
                """{
                  "cases": {
                    "film|frame": {
                      "scan_set": "Film",
                      "set_id": "frame",
                      "crops": [
                        {"name": "manual-01", "crop": [10, 20, 30, 40]}
                      ]
                    }
                  }
                }""",
                encoding="utf-8",
            )

            plan = review_viewers.read_crop_plan(path)

            self.assertEqual(plan[("Film", "frame")], [("manual-01", (10, 20, 30, 40))])
            self.assertIn("d100", review_viewers.DEFAULT_LEVELS)
            self.assertIn("d200", review_viewers.DEFAULT_LEVELS)
            self.assertEqual(review_viewers.DEFAULT_LEVELS[:3], ["d003", "d005", "d010"])

    def test_review_viewer_overview_is_small_and_marks_selected_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "overview.png"
            source = np.zeros((120, 180, 3), dtype=np.uint16)
            review_viewers.save_overview(
                output,
                source,
                (60, 40, 30, 30),
                "PS16 reference",
                "manual-01",
                90,
                force=True,
            )
            image = np.asarray(Image.open(output).convert("RGB"))
            self.assertLessEqual(max(image.shape[:2]), 90)
            self.assertTrue(np.any(np.all(image == np.array([255, 212, 0]), axis=2)))

    def test_context_crop_label_is_placed_outside_crop_box(self) -> None:
        image = Image.new("RGB", (900, 600), "white")
        draw = ImageDraw.Draw(image)
        rect = [150, 225, 174, 249]

        x, y = context_images.crop_label_position(draw, rect, "crop: manual-01", image.size)
        left, top, right, bottom = context_images.label_bounds(draw, (x, y), "crop: manual-01")
        overlaps_crop = not (right < rect[0] or left > rect[2] or bottom < rect[1] or top > rect[3])

        self.assertFalse(overlaps_crop)

    def test_report_site_context_paths_only_reads_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "frame").mkdir()
            write_png(root / "frame" / "context.png", textured_rgb(12, 12))
            (root / "frame" / "source.tif").write_bytes(b"not published")

            contexts = report_site.context_paths(root)

            self.assertEqual([path.name for path in contexts], ["context.png"])

    def test_report_site_places_color_legend_after_level_table_with_units(self) -> None:
        summary = report_site.LevelSummary(
            level="d030",
            rows=3,
            median_retained_mib=54.0,
            min_retained_mib=50.0,
            max_retained_mib=60.0,
            median_raw61_mib=68.0,
            median_size_pct=80.0,
            min_size_pct=70.0,
            max_size_pct=90.0,
            median_jxl_delta_e=0.12,
            p95_jxl_delta_e=0.16,
            median_raw_delta_e=5.0,
            median_color_ratio=0.031,
            median_jxl_structure_loss=0.24,
            median_raw_structure_loss=1.0,
            median_structure_ratio=0.24,
            verdicts={"ps16_jxl_likely_wins": 3},
            status="Passes current gates",
        )

        html = report_site.render_html(
            rows=[],
            summaries=[summary],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
        )

        self.assertLess(html.index("<h2>Level Summary</h2>"), html.index("<h2>Color Legend And Units</h2>"))
        self.assertLess(
            html.index("<h2>Color Legend And Units</h2>"),
            html.index("<h2>RAW61 Baseline By Frame</h2>"),
        )
        self.assertIn("80.0 % of RAW61", html)
        self.assertIn("54.0 MiB", html)
        self.assertIn("0.16 &Delta;E00", html)
        self.assertIn("0.03x RAW61", html)
        self.assertIn("error is 24.0% of PS16 high-frequency RMS", html)
        self.assertIn('class="chart-bar chart-bar-pass"', html)
        self.assertNotIn("<polyline", html)
        self.assertIn('class="table-scroll"', html)
        self.assertIn("@media (max-width: 700px)", html)

    def test_report_site_baseline_table_has_permanent_column_explanations(self) -> None:
        html = report_site.render_html(
            rows=[],
            summaries=[],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
        )

        baseline_table = html[html.index("<h2>RAW61 Baseline By Frame</h2>") :]
        self.assertIn('class="column-help-row"', baseline_table)
        self.assertIn("Scan collection or material label.", baseline_table)
        self.assertIn("this is not JXL codec loss", baseline_table)
        self.assertIn("not a direct percentage of lost information", baseline_table)
        self.assertIn("256 x 256-pixel patches", baseline_table)
        self.assertNotIn('data-full=', baseline_table)

    def test_report_site_level_table_has_help_row_and_lossless_reference(self) -> None:
        summary = report_site.LevelSummary(
            level="d030",
            rows=3,
            median_retained_mib=54.0,
            min_retained_mib=50.0,
            max_retained_mib=60.0,
            median_raw61_mib=68.0,
            median_size_pct=80.0,
            min_size_pct=70.0,
            max_size_pct=90.0,
            median_jxl_delta_e=0.12,
            p95_jxl_delta_e=0.16,
            median_raw_delta_e=5.0,
            median_color_ratio=0.031,
            median_jxl_structure_loss=0.24,
            median_raw_structure_loss=1.0,
            median_structure_ratio=0.24,
            verdicts={"ps16_jxl_likely_wins": 3},
            status="Passes current gates",
        )

        html = report_site.render_html(
            rows=[],
            summaries=[summary],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
        )

        self.assertIn('class="column-help-row"', html)
        self.assertIn('<span class="column-help">JPEG XL distance label.', html)
        self.assertNotIn('data-full=', html)
        self.assertIn("<strong>lossless</strong>", html)
        self.assertLess(html.index("<strong>lossless</strong>"), html.index("<strong>d030</strong>"))
        self.assertNotIn('class="bar"', html)

    def test_report_site_question_cards_include_answers_so_far(self) -> None:
        html = report_site.render_html(
            rows=[],
            summaries=[],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
        )

        self.assertEqual(html.count("<summary>Answer so far</summary>"), 4)
        self.assertIn("small color or tone losses hidden inside the orange mask", html)
        self.assertIn("Current complete rows favor PS16 JXL", html)
        self.assertIn("Candidate Comparisons", html)
        self.assertIn("one film material &times; frame &times; JXL distance", html)
        self.assertIn("Fully Measured Comparisons", html)
        self.assertIn("Median-size Budget Levels", html)
        self.assertIn("this is a size result, not a quality verdict", html)
        self.assertIn("This compares two archival workflows, not sensor resolution in isolation", html)
        self.assertIn("registered crop comparisons provided below", html)
        self.assertIn("patch color movement (small shifts in the measured average color of sampled image areas)", html)
        self.assertIn("the trained eye can still see grain/texture changes", html)

    def test_report_site_documents_adc_dng_jxl_caveats(self) -> None:
        html = report_site.render_html(
            rows=[],
            summaries=[],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
        )

        self.assertIn("<h2>ADC DNG/JXL</h2>", html)
        self.assertEqual(1, html.count('<details class="adc-disclosure">'))
        self.assertNotIn('<details class="adc-disclosure" open>', html)
        self.assertIn("Why ADC DNG/JXL Was Excluded", html)
        self.assertIn("Nine documented findings", html)
        self.assertIn("Stored image shape", html)
        self.assertIn("Crop origin / active placement", html)
        self.assertIn("<code>WhiteLevel</code>", html)
        self.assertIn("<code>OpcodeList2</code>", html)
        self.assertIn("RawTherapee compatibility", html)
        self.assertIn("Independent full-DNG decode", html)
        self.assertIn("Real edit and visual review", html)
        self.assertIn("Storage-budget coverage", html)
        self.assertIn("19200&times;12752", html)
        self.assertIn("Error loading file", html)
        self.assertNotIn("Why Negative-aware Preconditioning", html)
        self.assertNotIn("likely additional saving", html)
        self.assertNotIn("roughly <code>5-10%</code>", html)

    def test_report_site_includes_bounded_muimg_probe(self) -> None:
        probe = report_site.read_json_object(ROOT / "metadata/muimg_dng_jxl_probe.json")

        html = report_site.render_html(
            rows=[],
            summaries=[],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
            muimg_probe=probe,
        )

        self.assertIn("<h2>muimg Direct DNG/JXL Probe</h2>", html)
        self.assertIn("between d006 and d007 on this frame", html)
        self.assertIn("94.6% of its paired RAW61 size", html)
        self.assertIn("0 changed samples", html)
        self.assertIn("RawDataUniqueID", html)
        self.assertIn("all four sampled d007 main-image tiles used <strong>XYB</strong>", html)
        self.assertIn("not directly comparable with the report's post-RawTherapee RAW61 baselines", html)
        self.assertIn("RawTherapee 5.12", html)
        self.assertIn("JPEG XL-compressed image data inside DNG 1.7", html)
        self.assertIn("does not establish a general lack of DNG 1.7 support", html)
        self.assertIn("d001 main codestream is byte-identical to d003", html)
        self.assertIn("200 MiB cannot be dialled in by interpolation", html)
        self.assertIn("compression type <code>52546</code>", html)

    def test_report_site_states_practical_muimg_conclusion_for_qualified_corpus(self) -> None:
        probe = report_site.read_json_object(ROOT / "metadata/muimg_dng_jxl_probe.json")
        qualification = report_site.read_json_object(ROOT / "metadata/muimg_archive_qualification.json")

        html = report_site.render_html(
            rows=[],
            summaries=[],
            panels=[],
            contexts=[],
            output=Path("site/index.html"),
            muimg_probe=probe,
            muimg_qualification=qualification,
        )

        self.assertIn("Practical Archival Reading", html)
        self.assertIn("credible PS16 preservation candidate", html)
        self.assertIn("decoder diversity is still narrow", html)
        self.assertIn("If DNG 1.7/JPEG XL support becomes routine", html)
        self.assertIn("color-negative material is deliberately demanding here", html)
        self.assertIn("a reason for optimism, not direct proof", html)

    def test_report_site_panel_paths_includes_generated_non_manual_crops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            panel_dir = root / "film" / "frame"
            panel_dir.mkdir(parents=True)
            write_png(panel_dir / "d020_auto-detail_identity.png", textured_rgb(12, 12))
            write_png(panel_dir / "d020_center_identity.png", textured_rgb(12, 12))

            panels = report_site.panel_paths(root, root / "report" / "index.html")

            self.assertEqual(
                [path.name for path in panels],
                ["d020_auto-detail_identity.png", "d020_center_identity.png"],
            )

    def test_report_site_excludes_case_by_scan_set_or_slug(self) -> None:
        rows = [
            {"scan_set": "Private test set", "set_id": "PRIVATE_FRAME"},
            {"scan_set": "Kodak5035 H190-1983", "set_id": "_DSC6577"},
        ]
        excludes = {("private_test_set", "PRIVATE_FRAME")}

        filtered = report_site.filter_rows(rows, excludes)

        self.assertEqual([row["set_id"] for row in filtered], ["_DSC6577"])

    def test_report_site_places_contexts_in_matching_panel_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            panel_dir = root / "panels" / "film" / "frame"
            context_dir = root / "contexts" / "film" / "frame"
            panel_dir.mkdir(parents=True)
            context_dir.mkdir(parents=True)
            panel_path = panel_dir / "d025_manual-01_identity.png"
            context_path = context_dir / "ps16_reference_manual-01.png"
            write_png(panel_path, textured_rgb(12, 12))
            write_png(context_path, textured_rgb(12, 12))

            html = report_site.render_html(
                rows=[],
                summaries=[],
                panels=[panel_path],
                contexts=[context_path],
                output=root / "report" / "index.html",
            )

            self.assertIn("ps16_reference_manual-01.png", html)
            self.assertLess(html.index("ps16_reference_manual-01.png"), html.index("d025_manual-01_identity.png"))

    def test_report_site_includes_public_reproducibility_figures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            figures = root / "figures"
            figures.mkdir()
            public_figure = figures / "fadgi-negative35mm2-d005-density-hard-print.png"
            write_png(public_figure, textured_rgb(12, 12))

            html = report_site.render_html(
                rows=[],
                summaries=[],
                panels=[],
                contexts=[],
                output=root / "site" / "index.html",
                public_figures=[public_figure],
            )

            self.assertIn("Public Reproducibility Check", html)
            self.assertIn("do not contribute rows to the storage break-even verdict", html)
            self.assertIn("fadgi-negative35mm2-d005-density-hard-print.png", html)

    def test_report_site_embeds_inline_crop_viewer_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            viewer_dir = root / "site" / "assets" / "review-viewers" / "synthetic_scan" / "frame001"
            viewer_dir.mkdir(parents=True)
            viewer_index = viewer_dir / "index.html"
            viewer_index.write_text("<html></html>", encoding="utf-8")
            for name in [
                "reference.png",
                "raw61.png",
                "jxl_d020.png",
                "jxl_d200.png",
                "overview_reference.png",
                "overview_raw61.png",
                "overview_jxl_d020.png",
                "overview_jxl_d200.png",
            ]:
                write_png(viewer_dir / name, textured_rgb(12, 12))
            (viewer_dir / "metadata.json").write_text(
                """{
                  "labels": {
                    "raw61": "RAW61 local aligned",
                    "jxl_d020": "PS16 JXL d020",
                    "jxl_d200": "PS16 JXL d200"
                  },
                  "overviews": {
                    "reference": "overview_reference.png",
                    "ps16_lossless": "overview_reference.png",
                    "raw61": "overview_raw61.png",
                    "jxl_d020": "overview_jxl_d020.png",
                    "jxl_d200": "overview_jxl_d200.png"
                  },
                  "scan_set": "Synthetic Scan",
                  "set_id": "frame001",
                  "transform": "identity",
                  "crop": [1, 2, 3, 4],
                  "local_raw61_alignment": {"applied": true, "shift_x_px": 1, "shift_y_px": -1}
                }""",
                encoding="utf-8",
            )

            html = report_site.render_html(
                rows=[
                    {
                        "scan_set": "Synthetic Scan",
                        "set_id": "frame001",
                        "level": "d020",
                        "raw61_size_mib": "68.25",
                        "retained_size_mib": "54.5",
                    }
                ],
                summaries=[],
                panels=[],
                contexts=[],
                output=root / "site" / "index.html",
                viewers=[viewer_index],
            )

            self.assertIn('id="cropWorkspace"', html)
            self.assertIn('id="cropFullscreen"', html)
            self.assertIn('workspace.requestFullscreen()', html)
            self.assertIn(
                'else {\n        resetView();\n        await workspace.requestFullscreen();',
                html,
            )
            self.assertIn(
                'if (document.fullscreenElement === workspace) resetView();',
                html,
            )
            self.assertIn('window.requestAnimationFrame(() => {', html)
            self.assertIn('aria-labelledby="cropViewerTitle"', html)
            self.assertNotIn('id="cropModal"', html)
            self.assertNotIn('data-open-crop-viewer', html)
            self.assertIn('"key": "ps16_lossless"', html)
            self.assertIn('"key": "jxl_d200"', html)
            self.assertNotIn('"key": "raw61"', html)
            self.assertIn('"referenceStorageMib": 68.25', html)
            self.assertIn('"referenceLabel": "RAW61 local aligned"', html)
            self.assertIn('"storageMib": 54.5', html)
            self.assertIn('"storageKind": "encoded JXL"', html)
            self.assertIn('"referenceOverview": "assets/review-viewers/synthetic_scan/frame001/overview_raw61.png"', html)
            self.assertIn('"overview": "assets/review-viewers/synthetic_scan/frame001/overview_jxl_d200.png"', html)
            self.assertIn("drawOverview(state.referenceOverviewImage", html)
            self.assertIn('`${candidate.label} over RAW61`', html)
            self.assertIn('currentViewer().referenceLabel || "RAW61 local aligned"', html)
            self.assertIn("hard visual check", html)
            self.assertIn('let activeChoiceList = "film";', html)
            self.assertIn('let workspaceActive = false;', html)
            self.assertIn('workspaceActive = workspace.contains(event.target);', html)
            self.assertIn('if (!workspaceActive && !workspace.contains(document.activeElement)) return;', html)
            self.assertIn('button.addEventListener("focus", () => { activeChoiceList = "quality"; });', html)
            self.assertIn('role.textContent = [roleLabel, sizeLabel].filter(Boolean).join(" | ");', html)
            self.assertIn('if (event.key === "ArrowRight")', html)
            self.assertIn("moveViewer(1, true)", html)
            self.assertIn('if (event.key === "ArrowDown")', html)
            self.assertIn(
                'function setCandidate(key) {\n      state.candidateKey = key;\n      renderQualityList();',
                html,
            )
            self.assertNotIn(
                'function setCandidate(key) {\n      state.candidateKey = key;\n      resetView();',
                html,
            )

    def test_report_site_replaces_visual_review_items_with_inline_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            viewer_dir = root / "site" / "assets" / "review-viewers" / "synthetic_scan" / "frame001"
            viewer_dir.mkdir(parents=True)
            viewer_index = viewer_dir / "index.html"
            viewer_index.write_text("<html></html>", encoding="utf-8")
            for name in ["reference.png", "raw61.png", "jxl_d020.png"]:
                write_png(viewer_dir / name, textured_rgb(12, 12))
            (viewer_dir / "metadata.json").write_text(
                """{
                  "labels": {"raw61": "RAW61 local aligned", "jxl_d020": "PS16 JXL d020"},
                  "scan_set": "Synthetic Scan",
                  "set_id": "frame001"
                }""",
                encoding="utf-8",
            )

            html = report_site.render_html(
                rows=[],
                summaries=[],
                panels=[],
                contexts=[],
                output=root / "site" / "index.html",
                viewers=[viewer_index],
            )

            self.assertIn('class="crop-workspace"', html)
            self.assertNotIn('class="review-item"', html)
            self.assertNotIn("Open fullscreen crop viewer", html)
            self.assertNotIn('class="panel-group review-group"', html)

    def test_report_site_groups_nested_crop_viewers_by_case_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            viewer_dir = root / "site" / "assets" / "review-viewers" / "synthetic_scan" / "frame001" / "manual-01"
            context_dir = root / "site" / "assets" / "review-contexts" / "synthetic_scan" / "frame001"
            viewer_dir.mkdir(parents=True)
            context_dir.mkdir(parents=True)
            viewer_index = viewer_dir / "index.html"
            viewer_index.write_text("<html></html>", encoding="utf-8")
            for name in ["reference.png", "raw61.png", "jxl_d100.png", "jxl_d200.png"]:
                write_png(viewer_dir / name, textured_rgb(12, 12))
            (viewer_dir / "metadata.json").write_text(
                """{
                  "labels": {
                    "raw61": "RAW61 local aligned",
                    "jxl_d100": "PS16 JXL d100",
                    "jxl_d200": "PS16 JXL d200"
                  },
                  "scan_set": "Synthetic Scan",
                  "set_id": "frame001",
                  "crop_name": "manual-01",
                  "transform": "identity",
                  "crop": [1, 2, 3, 4]
                }""",
                encoding="utf-8",
            )
            context_path = context_dir / "ps16_reference_manual-01.png"
            write_png(context_path, textured_rgb(12, 12))

            html = report_site.render_html(
                rows=[],
                summaries=[],
                panels=[],
                contexts=[context_path],
                output=root / "site" / "index.html",
                viewers=[viewer_index],
            )

            self.assertIn("synthetic_scan/frame001", report_site.viewer_groups([viewer_index]))
            self.assertIn("Synthetic Scan / frame001 / manual-01", html)
            self.assertIn('"cropName": "manual-01"', html)
            self.assertIn('"transform": "identity"', html)
            self.assertIn('"key": "jxl_d100"', html)
            self.assertIn('"key": "jxl_d200"', html)
            self.assertIn('class="crop-workspace"', html)
            self.assertNotIn("Open fullscreen crop viewer", html)
            self.assertNotIn('class="review-item"', html)

    def test_report_site_prefers_nested_crop_viewers_over_legacy_flat_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            viewer_root = root / "site" / "assets" / "review-viewers"
            flat_dir = viewer_root / "synthetic_scan" / "frame001"
            nested_dir = flat_dir / "manual-01"
            flat_dir.mkdir(parents=True)
            nested_dir.mkdir(parents=True)
            flat_index = flat_dir / "index.html"
            nested_index = nested_dir / "index.html"
            flat_index.write_text("<html></html>", encoding="utf-8")
            nested_index.write_text("<html></html>", encoding="utf-8")

            paths = report_site.viewer_paths(viewer_root)

            self.assertEqual(paths, [nested_index])

    def test_crop_guide_reads_multiple_exact_magenta_markers(self) -> None:
        guide = np.zeros((110, 140, 3), dtype=np.uint8)
        guide[51:57, 21:27] = (255, 0, 255)
        guide[81:87, 101:107] = (255, 0, 255)
        metadata = {
            "marker_rgb": [255, 0, 255],
            "image_offset": [0, 10],
            "display_width": 140,
            "display_height": 100,
            "source_width": 1400,
            "source_height": 1000,
        }

        crops = crop_guides.marker_crops(guide, metadata, crop_size=200, minimum_marker_pixels=4)

        self.assertEqual(len(crops), 2)
        self.assertEqual([item["name"] for item in crops], ["manual-01", "manual-02"])
        self.assertEqual(crops[0]["marker_display"], [24, 44])
        self.assertEqual(crops[1]["marker_display"], [104, 74])

    def test_report_site_marks_under_budget_warn_color_as_passing_current_gates(self) -> None:
        summary = report_site.LevelSummary(
            level="d030",
            rows=3,
            median_retained_mib=54.0,
            min_retained_mib=50.0,
            max_retained_mib=60.0,
            median_raw61_mib=68.0,
            median_size_pct=80.0,
            min_size_pct=70.0,
            max_size_pct=90.0,
            median_jxl_delta_e=1.2,
            p95_jxl_delta_e=1.7,
            median_raw_delta_e=5.0,
            median_color_ratio=0.34,
            median_jxl_structure_loss=0.2,
            median_raw_structure_loss=1.0,
            median_structure_ratio=0.2,
            verdicts={"ps16_jxl_likely_wins": 3},
            status="",
        )

        self.assertEqual(report_site.status_for(summary), "Passes current gates")

    def test_report_site_excludes_aggressive_visual_stress_levels_from_gate(self) -> None:
        summary = report_site.LevelSummary(
            level="d200",
            rows=3,
            median_retained_mib=8.0,
            min_retained_mib=7.0,
            max_retained_mib=9.0,
            median_raw61_mib=68.0,
            median_size_pct=12.0,
            min_size_pct=10.0,
            max_size_pct=14.0,
            median_jxl_delta_e=0.5,
            p95_jxl_delta_e=0.7,
            median_raw_delta_e=5.0,
            median_color_ratio=0.14,
            median_jxl_structure_loss=0.2,
            median_raw_structure_loss=1.0,
            median_structure_ratio=0.2,
            verdicts={"ps16_jxl_likely_wins": 3},
            status="",
        )

        self.assertEqual(report_site.status_for(summary), "Visual stress only")

    def test_rendered_matrix_merge_replaces_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rows.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["scan_set", "set_id", "level", "value"])
                writer.writeheader()
                writer.writerow({"scan_set": "a", "set_id": "one", "level": "d020", "value": "old"})
                writer.writerow({"scan_set": "a", "set_id": "one", "level": "d030", "value": "kept"})

            merged = rendered_matrix.merge_rows(
                path,
                [{"scan_set": "a", "set_id": "one", "level": "d020", "value": "new"}],
                ("scan_set", "set_id", "level"),
            )

        self.assertEqual(
            merged,
            [
                {"scan_set": "a", "set_id": "one", "level": "d030", "value": "kept"},
                {"scan_set": "a", "set_id": "one", "level": "d020", "value": "new"},
            ],
        )

    def test_rendered_matrix_encodes_a_container_with_the_source_icc(self) -> None:
        command = rendered_matrix.encode_command(
            "cjxl",
            Path("reference.ppm"),
            Path("candidate.jxl"),
            Path("reference.icc"),
            "d030",
            7,
        )

        self.assertIn("--container=1", command)
        self.assertIn("icc_pathname=reference.icc", command)

    def test_rendered_matrix_metadata_copy_is_curated_from_the_rendered_tiff(self) -> None:
        command = rendered_matrix.metadata_copy_command(
            "exiftool", Path("master.tif"), Path("candidate.jxl")
        )

        self.assertEqual(command[:5], ["exiftool", "-m", "-overwrite_original", "-TagsFromFile", "master.tif"])
        self.assertIn("-LensModel", command)
        self.assertIn("-DateTimeOriginal", command)
        self.assertNotIn("-all:all", command)

    def test_structure_metrics_merge_replaces_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rows.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["scan_set", "set_id", "level", "scope", "value"])
                writer.writeheader()
                writer.writerow({"scan_set": "a", "set_id": "one", "level": "d020", "scope": "full", "value": "old"})
                writer.writerow({"scan_set": "a", "set_id": "one", "level": "d030", "scope": "full", "value": "kept"})

            merged = structure_runner.merge_rows(
                path,
                [{"scan_set": "a", "set_id": "one", "level": "d020", "scope": "full", "value": "new"}],
                ("scan_set", "set_id", "level", "scope"),
            )

        self.assertEqual(
            merged,
            [
                {"scan_set": "a", "set_id": "one", "level": "d030", "scope": "full", "value": "kept"},
                {"scan_set": "a", "set_id": "one", "level": "d020", "scope": "full", "value": "new"},
            ],
        )

    def test_uint8_tiff_fallback_can_write_without_tifffile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tiny.tif"
            write_rgb_tiff(path, textured_rgb(16, 16))
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
