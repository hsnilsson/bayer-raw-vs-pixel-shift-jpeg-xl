from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_negpy_extreme_inversions import (  # noqa: E402
    BRIGHT_HIGHLIGHT_MODE_KEY,
    DEEP_SHADOW_MODE_KEY,
    MODE_KEY,
    align_raw61_crop,
    crop_array,
    crop_to_uint16,
    merge_mode,
    merge_tail_modes,
    mode_for_scan,
    output_mapping,
    ppm_memmap,
    reference_tail_bounds,
    render_tail_view,
    tail_statistics,
)


class NegPyExtremeInversionTests(unittest.TestCase):
    def test_output_mapping_preserves_layer_keys(self) -> None:
        metadata = {
            "images_by_transform": {
                "identity": {
                    "reference": "reference.png",
                    "ps16_lossless": "reference.png",
                    "raw61": "raw61.png",
                    "jxl_d025": "jxl_d025.png",
                }
            }
        }
        self.assertEqual(
            output_mapping(metadata),
            {
                "reference": f"reference_{MODE_KEY}.png",
                "ps16_lossless": f"reference_{MODE_KEY}.png",
                "raw61": f"raw61_{MODE_KEY}.png",
                "jxl_d025": f"jxl_d025_{MODE_KEY}.png",
            },
        )

    def test_merge_mode_replaces_an_existing_entry_without_removing_others(self) -> None:
        metadata = {
            "view_modes": [
                {"key": "identity", "label": "Normal"},
                {"key": MODE_KEY, "label": "Old"},
            ],
            "images_by_transform": {"identity": {"reference": "reference.png"}},
        }
        result = merge_mode(metadata, {"reference": "new.png"}, {"revision": "abc"})
        self.assertEqual([mode["key"] for mode in result["view_modes"]], ["identity", MODE_KEY])
        self.assertEqual(result["images_by_transform"][MODE_KEY], {"reference": "new.png"})
        self.assertEqual(result[MODE_KEY], {"revision": "abc"})

    def test_merge_tail_modes_replaces_tail_entries_and_keeps_other_modes(self) -> None:
        metadata = {
            "view_modes": [
                {"key": "identity", "label": "Normal"},
                {"key": DEEP_SHADOW_MODE_KEY, "label": "Old"},
            ],
            "images_by_transform": {"identity": {"reference": "reference.png"}},
        }
        images = {
            DEEP_SHADOW_MODE_KEY: {"reference": "shadow.png"},
            BRIGHT_HIGHLIGHT_MODE_KEY: {"reference": "highlight.png"},
        }

        result = merge_tail_modes(metadata, images, {"source_mode": MODE_KEY})

        self.assertEqual(
            [mode["key"] for mode in result["view_modes"]],
            ["identity", DEEP_SHADOW_MODE_KEY, BRIGHT_HIGHLIGHT_MODE_KEY],
        )
        self.assertEqual(result["images_by_transform"][DEEP_SHADOW_MODE_KEY], images[DEEP_SHADOW_MODE_KEY])
        self.assertEqual(result["negpy_tail_diagnostics"], {"source_mode": MODE_KEY})

    def test_tail_views_use_reference_locked_bounds_and_isolate_opposite_ends(self) -> None:
        ramp = np.linspace(0, 65535, 10_000, dtype=np.uint16).reshape(100, 100)
        reference = np.repeat(ramp[:, :, None], 3, axis=2)
        bounds = reference_tail_bounds(reference)

        shadow = render_tail_view(reference, bounds, DEEP_SHADOW_MODE_KEY)
        highlight = render_tail_view(reference, bounds, BRIGHT_HIGHLIGHT_MODE_KEY)

        self.assertGreater(int(shadow[0, 0, 0]), 65000)
        self.assertEqual(int(shadow[-1, -1, 0]), 0)
        self.assertEqual(int(highlight[0, 0, 0]), 0)
        self.assertGreater(int(highlight[-1, -1, 0]), 65000)
        statistics = tail_statistics(reference, bounds)
        self.assertAlmostEqual(statistics["below_reference_shadow_cutoff_percent"], 1.0, delta=0.05)
        self.assertAlmostEqual(statistics["above_reference_highlight_cutoff_percent"], 1.0, delta=0.05)

    def test_shadow_tail_preserves_visible_chromaticity(self) -> None:
        ramp = np.linspace(0, 65535, 10_000, dtype=np.uint16).reshape(100, 100)
        reference = np.repeat(ramp[:, :, None], 3, axis=2)
        reference[0, 0] = [64, 32, 16]
        bounds = reference_tail_bounds(reference)

        shadow = render_tail_view(reference, bounds, DEEP_SHADOW_MODE_KEY)

        self.assertGreater(int(shadow[0, 0, 0]), int(shadow[0, 0, 1]))
        self.assertGreater(int(shadow[0, 0, 1]), int(shadow[0, 0, 2]))
        np.testing.assert_array_equal(shadow[50, 50], [0, 0, 0])

    def test_tied_tail_threshold_marks_the_entire_quantized_plateau(self) -> None:
        reference = np.full((100, 100, 3), 32768, dtype=np.uint16)
        reference[:3, :, :] = 1024
        bounds = reference_tail_bounds(reference)

        shadow = render_tail_view(reference, bounds, DEEP_SHADOW_MODE_KEY)

        self.assertGreater(int(shadow[0, 0, 0]), 65000)
        np.testing.assert_array_equal(shadow[50, 50], [0, 0, 0])

    def test_ppm_memmap_reads_16_bit_rgb_without_loading_the_frame(self) -> None:
        pixels = np.arange(3 * 4 * 3, dtype=np.uint16).reshape(3, 4, 3)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.ppm"
            path.write_bytes(b"P6\n# generated\n4 3\n65535\n" + pixels.astype(">u2").tobytes())
            mapped, maximum = ppm_memmap(path)
            self.assertEqual(maximum, 65535)
            np.testing.assert_array_equal(np.asarray(mapped), pixels)
            np.testing.assert_array_equal(crop_array(mapped, [1, 1, 2, 2]), pixels[1:3, 1:3])
            mapped._mmap.close()

    def test_crop_promotes_8_bit_samples_to_full_uint16_range(self) -> None:
        crop = np.array([[[0, 1, 255]]], dtype=np.uint8)

        promoted = crop_to_uint16(crop)

        self.assertEqual(promoted.dtype, np.uint16)
        self.assertEqual(promoted.tolist(), [[[0, 257, 65535]]])

    def test_raw61_crop_uses_saved_local_alignment(self) -> None:
        crop = np.zeros((5, 5, 3), dtype=np.uint16)
        crop[2, 2] = 65535
        metadata = {
            "local_raw61_alignment": {
                "shift_x_px": 1.0,
                "shift_y_px": -1.0,
                "applied": True,
            }
        }

        aligned = align_raw61_crop(crop, metadata)

        np.testing.assert_array_equal(aligned[1, 3], [65535, 65535, 65535])
        np.testing.assert_array_equal(aligned[2, 2], [0, 0, 0])

    def test_raw61_crop_is_unchanged_when_alignment_was_not_applied(self) -> None:
        crop = np.arange(27, dtype=np.uint16).reshape(3, 3, 3)
        metadata = {"local_raw61_alignment": {"applied": False}}

        self.assertIs(align_raw61_crop(crop, metadata), crop)

    def test_process_mode_uses_bw_only_for_the_adox_target(self) -> None:
        self.assertEqual(mode_for_scan("adox_vlad_resolution_target"), "B&W Negative")
        self.assertEqual(mode_for_scan("Kodak Gold 200-5 1997"), "Color Negative")

    def test_generated_corpus_keeps_old_modes_and_uses_16_bit_768px_pngs(self) -> None:
        metadata_paths = sorted((ROOT / "site/assets/review-viewers").rglob("metadata.json"))
        self.assertEqual(len(metadata_paths), 26)
        generated: set[Path] = set()
        tail_generated = {
            DEEP_SHADOW_MODE_KEY: set(),
            BRIGHT_HIGHLIGHT_MODE_KEY: set(),
        }
        old_modes = {"negative_density_hard_print", "negative_density_hard_shadow_recovery"}

        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            modes = [mode["key"] for mode in metadata["view_modes"]]
            self.assertEqual(modes.count(MODE_KEY), 1, metadata_path)
            self.assertEqual(modes.count(DEEP_SHADOW_MODE_KEY), 1, metadata_path)
            self.assertEqual(modes.count(BRIGHT_HIGHLIGHT_MODE_KEY), 1, metadata_path)
            self.assertTrue(old_modes.issubset(modes), metadata_path)
            self.assertEqual(
                metadata[MODE_KEY]["raw61_alignment"],
                metadata["local_raw61_alignment"],
                metadata_path,
            )
            for relative in set(metadata["images_by_transform"][MODE_KEY].values()):
                image_path = metadata_path.parent / relative
                generated.add(image_path)
                with image_path.open("rb") as handle:
                    header = handle.read(25)
                self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", image_path)
                self.assertEqual(struct.unpack(">II", header[16:24]), (768, 768), image_path)
                self.assertEqual(header[24], 16, image_path)

            tail_metadata = metadata["negpy_tail_diagnostics"]
            self.assertEqual(tail_metadata["source_mode"], MODE_KEY, metadata_path)
            self.assertIn("reference", tail_metadata["layers"], metadata_path)
            self.assertIn("raw61", tail_metadata["layers"], metadata_path)
            for mode_key in tail_generated:
                mapping = metadata["images_by_transform"][mode_key]
                self.assertEqual(set(mapping), set(metadata["images_by_transform"][MODE_KEY]), metadata_path)
                for relative in set(mapping.values()):
                    image_path = metadata_path.parent / relative
                    tail_generated[mode_key].add(image_path)
                    with image_path.open("rb") as handle:
                        header = handle.read(25)
                    self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", image_path)
                    self.assertEqual(struct.unpack(">II", header[16:24]), (768, 768), image_path)
                    self.assertEqual(header[24], 16, image_path)

        self.assertEqual(len(generated), 246)
        self.assertEqual(len(tail_generated[DEEP_SHADOW_MODE_KEY]), 246)
        self.assertEqual(len(tail_generated[BRIGHT_HIGHLIGHT_MODE_KEY]), 246)


if __name__ == "__main__":
    unittest.main()
