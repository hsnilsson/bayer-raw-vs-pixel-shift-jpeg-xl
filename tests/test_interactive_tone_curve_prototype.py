from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_interactive_tone_curve_prototype as prototype  # noqa: E402


class InteractiveToneCurvePrototypeTests(unittest.TestCase):
    def test_rgb16_encoding_preserves_values_beyond_eight_bit_steps(self) -> None:
        source = np.array([[[0, 1, 257], [258, 32768, 65535]]], dtype=np.uint16)

        encoded = np.frombuffer(prototype.encode_rgb16le(source), dtype="<u2").reshape(source.shape)

        np.testing.assert_array_equal(encoded, source)

    def test_write_prototype_keeps_high_precision_sidecars_and_scope_boundary(self) -> None:
        reference = np.arange(4 * 5 * 3, dtype=np.uint16).reshape(4, 5, 3) * 997
        candidate = np.minimum(reference.astype(np.uint32) + 23, 65535).astype(np.uint16)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)

            index_path = prototype.write_prototype(
                reference,
                candidate,
                output,
                title="Representative crop",
                reference_label="Reference",
                candidate_label="Candidate",
                crop_spec=(10, 20, 5, 4),
            )

            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            html = index_path.read_text(encoding="utf-8")
            self.assertEqual((output / "reference.rgb16le").stat().st_size, reference.size * 2)
            self.assertEqual((output / "candidate.rgb16le").stat().st_size, candidate.size * 2)
            self.assertEqual(metadata["stored_precision_bits"], 16)
            self.assertEqual(metadata["crop"], [10, 20, 5, 4])
            self.assertIn("fixed rendered RGB chain", metadata["scope_note"])
            self.assertIn("original raw files", metadata["scope_note"])
            self.assertIn('id="curveCanvas"', html)
            self.assertIn('id="curve50"', html)
            self.assertIn('id="histogramCanvas"', html)
            self.assertIn("blackClipped", html)
            self.assertIn("source buffers: 16-bit rgb", html.lower())

    def test_write_prototype_rejects_eight_bit_inputs(self) -> None:
        reference = np.zeros((2, 2, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaisesRegex(ValueError, "above 8-bit"):
            prototype.write_prototype(
                reference,
                reference,
                Path(temp_dir),
                title="Too shallow",
                reference_label="Reference",
                candidate_label="Candidate",
                crop_spec=(0, 0, 2, 2),
            )


if __name__ == "__main__":
    unittest.main()
