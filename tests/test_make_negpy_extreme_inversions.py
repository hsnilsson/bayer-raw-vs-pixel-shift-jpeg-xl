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

    def test_process_mode_uses_bw_only_for_the_adox_target(self) -> None:
        self.assertEqual(mode_for_scan("adox_vlad_resolution_target"), "B&W Negative")
        self.assertEqual(mode_for_scan("Kodak Gold 200-5 1997"), "Color Negative")

    def test_generated_corpus_keeps_old_modes_and_uses_16_bit_768px_pngs(self) -> None:
        metadata_paths = sorted((ROOT / "site/assets/review-viewers").rglob("metadata.json"))
        self.assertEqual(len(metadata_paths), 26)
        generated: set[Path] = set()
        old_modes = {"negative_density_hard_print", "negative_density_hard_shadow_recovery"}

        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            modes = [mode["key"] for mode in metadata["view_modes"]]
            self.assertEqual(modes.count(MODE_KEY), 1, metadata_path)
            self.assertTrue(old_modes.issubset(modes), metadata_path)
            for relative in set(metadata["images_by_transform"][MODE_KEY].values()):
                image_path = metadata_path.parent / relative
                generated.add(image_path)
                with image_path.open("rb") as handle:
                    header = handle.read(25)
                self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", image_path)
                self.assertEqual(struct.unpack(">II", header[16:24]), (768, 768), image_path)
                self.assertEqual(header[24], 16, image_path)

        self.assertEqual(len(generated), 246)


if __name__ == "__main__":
    unittest.main()
