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
    MODE_KEY,
    align_raw61_crop,
    crop_array,
    crop_to_uint16,
    merge_mode,
    mode_for_scan,
    output_mapping,
    ppm_memmap,
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

        rgb16_metadata = {
            "rgb16": {
                "sources": {
                    "reference": "reference.rgb16le",
                    "ps16_lossless": "reference.rgb16le",
                    "raw61": "raw61.rgb16le",
                    "jxl_d025": "jxl_d025.rgb16le",
                }
            }
        }
        self.assertEqual(
            output_mapping(rgb16_metadata),
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

    def test_generated_corpus_declares_current_modes_and_precision(self) -> None:
        metadata_paths = sorted((ROOT / "site/assets/review-viewers").rglob("metadata.json"))
        self.assertEqual(len(metadata_paths), 22)
        generated: set[Path] = set()
        verified = 0
        old_modes = {"negative_density_hard_print", "negative_density_hard_shadow_recovery"}

        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            modes = [mode["key"] for mode in metadata["view_modes"]]
            if metadata.get("schema") == 3:
                verified += 1
                self.assertNotIn(MODE_KEY, modes, metadata_path)
                self.assertNotIn(MODE_KEY, metadata, metadata_path)
                self.assertTrue(old_modes.issubset(modes), metadata_path)
                self.assertEqual(metadata["rgb16"]["bytes_per_sample"], 2)
                self.assertTrue(metadata["source_profile"]["icc_sha256"])
                continue
            self.assertEqual(modes.count(MODE_KEY), 1, metadata_path)
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

        self.assertEqual(verified + sum(json.loads(p.read_text(encoding="utf-8")).get("schema") != 3 for p in metadata_paths), 22)
        if not verified:
            self.assertGreater(len(generated), 200)


if __name__ == "__main__":
    unittest.main()
