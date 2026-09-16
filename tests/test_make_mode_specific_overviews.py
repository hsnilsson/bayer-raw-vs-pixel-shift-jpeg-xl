from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_mode_specific_overviews import (  # noqa: E402
    apply_channel_lut,
    fit_channel_lut,
    generate_viewer_previews,
    preview_filename,
)


class ModeSpecificOverviewTests(unittest.TestCase):
    def test_lut_reproduces_a_per_channel_inversion(self) -> None:
        ramp = np.arange(256, dtype=np.uint8)
        source = np.stack([ramp, ramp, ramp], axis=1).reshape(16, 16, 3)
        target = 255 - source

        result = apply_channel_lut(source, fit_channel_lut(source, target))

        np.testing.assert_array_equal(result, target)

    def test_preview_names_share_the_reference_layer(self) -> None:
        self.assertEqual(preview_filename("reference", "hard"), "overview_reference_hard.png")
        self.assertEqual(preview_filename("ps16_lossless", "hard"), "overview_reference_hard.png")
        self.assertEqual(preview_filename("raw61", "hard"), "overview_raw61_hard.png")

    def test_generator_preserves_identity_and_adds_mode_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            base = np.zeros((24, 36, 3), dtype=np.uint8)
            base[:, :, 0] = np.arange(36, dtype=np.uint8)
            base[:, :, 1] = 80
            base[:, :, 2] = 160
            crop = np.tile(np.arange(16, dtype=np.uint8).reshape(4, 4, 1), (1, 1, 3)) * 16
            Image.fromarray(base, mode="RGB").save(directory / "overview_reference.png")
            Image.fromarray(crop, mode="RGB").save(directory / "reference.png")
            Image.fromarray(255 - crop, mode="RGB").save(directory / "reference_inverted.png")
            metadata = {
                "labels": {"reference": "PS16 reference", "ps16_lossless": "PS16 lossless / reference"},
                "crop_name": "manual-01",
                "overviews": {
                    "reference": "overview_reference.png",
                    "ps16_lossless": "overview_reference.png",
                },
                "view_modes": [{"key": "identity"}, {"key": "inverted"}],
                "images_by_transform": {
                    "identity": {"reference": "reference.png", "ps16_lossless": "reference.png"},
                    "inverted": {
                        "reference": "reference_inverted.png",
                        "ps16_lossless": "reference_inverted.png",
                    },
                },
            }
            metadata_path = directory / "metadata.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            count = generate_viewer_previews(metadata_path, force=False)

            self.assertEqual(count, 1)
            updated = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["overviews_by_transform"]["identity"], metadata["overviews"])
            self.assertEqual(
                updated["overviews_by_transform"]["inverted"]["reference"],
                "overview_reference_inverted.png",
            )
            self.assertEqual(
                updated["overviews_by_transform"]["inverted"]["ps16_lossless"],
                "overview_reference_inverted.png",
            )
            output = directory / "overview_reference_inverted.png"
            with output.open("rb") as handle:
                header = handle.read(25)
            self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", header[16:24]), (36, 24))
            self.assertEqual(header[24], 8)

    def test_generated_corpus_has_small_preview_for_every_available_mode_layer(self) -> None:
        metadata_paths = sorted((ROOT / "site/assets/review-viewers").rglob("metadata.json"))
        self.assertEqual(len(metadata_paths), 22)
        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            overview_sets = metadata.get("overviews_by_transform", {})
            image_sets = metadata.get("images_by_transform", {})
            rgb16 = metadata.get("rgb16", {})
            rgb16_modes = set(rgb16.get("transforms", []))
            for mode in metadata["view_modes"]:
                mode_key = mode["key"]
                self.assertIn(mode_key, overview_sets, metadata_path)
                layers = rgb16.get("sources", {}) if mode_key in rgb16_modes else image_sets[mode_key]
                for key in layers:
                    self.assertIn(key, overview_sets[mode_key], (metadata_path, mode_key, key))
                    image_path = metadata_path.parent / overview_sets[mode_key][key]
                    with image_path.open("rb") as handle:
                        header = handle.read(25)
                    self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", image_path)
                    width, height = struct.unpack(">II", header[16:24])
                    self.assertLessEqual(max(width, height), 360, image_path)
                    self.assertEqual(header[24], 8, image_path)


if __name__ == "__main__":
    unittest.main()
