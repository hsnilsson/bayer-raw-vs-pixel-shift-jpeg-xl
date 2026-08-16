from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import jxl_archive_test  # noqa: E402
import make_public_crop_panels  # noqa: E402
import run_public_latitude_v2  # noqa: E402


class MetricTests(unittest.TestCase):
    def test_subunit_float_difference_is_not_exact(self) -> None:
        reference = np.array([[[0.0]]], dtype=np.float32)
        candidate = np.array([[[0.5]]], dtype=np.float32)

        result = jxl_archive_test.compute_metrics(reference, candidate, peak=1)

        self.assertFalse(result["exact"])
        self.assertEqual(result["max_error"], 0.5)

    def test_integer_max_error_remains_an_integer(self) -> None:
        reference = np.array([[[0]]], dtype=np.uint16)
        candidate = np.array([[[2]]], dtype=np.uint16)

        result = jxl_archive_test.compute_metrics(reference, candidate, peak=65535)

        self.assertIsInstance(result["max_error"], int)
        self.assertEqual(result["max_error"], 2)


class DistanceArgumentTests(unittest.TestCase):
    def test_explicit_distance_does_not_include_defaults(self) -> None:
        args = jxl_archive_test.build_parser().parse_args(
            ["encode-test", "reference.png", "--distance", "0.05"]
        )

        self.assertEqual(args.distance, ["0.05"])

    def test_absent_distance_is_deferred_to_main(self) -> None:
        args = jxl_archive_test.build_parser().parse_args(
            ["encode-test", "reference.png"]
        )

        self.assertIsNone(args.distance)

    def test_main_applies_defaults_only_when_distance_is_absent(self) -> None:
        observed: list[str] = []

        def fake_encode(args):
            observed.extend(args.distance)
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "reference.png"
            reference.write_bytes(b"placeholder")
            with (
                mock.patch.object(jxl_archive_test, "encode_decode", side_effect=fake_encode),
                mock.patch.object(jxl_archive_test, "compare"),
            ):
                result = jxl_archive_test.main(["encode-test", str(reference)])

        self.assertEqual(result, 0)
        self.assertEqual(observed, ["0.5", "1.0"])


class PpmReaderTests(unittest.TestCase):
    def test_first_raster_byte_may_be_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "leading-whitespace.ppm"
            path.write_bytes(b"P6\n1 1\n255\n" + bytes([10, 20, 30]))

            image = make_public_crop_panels.read_ppm(path)

        self.assertEqual(image.tolist(), [[[10, 20, 30]]])

    def test_raster_length_must_match_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trailing-data.ppm"
            path.write_bytes(b"P6\n1 1\n255\n" + bytes([1, 2, 3, 4]))

            with self.assertRaisesRegex(ValueError, "unexpected PPM raster length"):
                make_public_crop_panels.read_ppm(path)


class ReuseProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.versions: dict[str, object] = {
            "python": "test-python",
            "platform": "test-platform",
            "executable": "test-python",
            "packages": {},
            "tools": {},
            "git": {},
        }
        self.context: dict[str, object] = {
            "pipeline": "test",
            "parameters": {"distance": ["0.05"]},
            "inputs": [],
            "code": [],
            "environment": {},
        }

    def create_provenance(self, out_dir: Path) -> None:
        (out_dir / "metrics.csv").write_text("name,value\ntest,1\n", encoding="utf-8")
        (out_dir / "metrics.json").write_text("[]\n", encoding="utf-8")
        run_public_latitude_v2.write_run_provenance(
            out_dir,
            self.context,
            self.versions,
        )

    def test_valid_reuse_does_not_rewrite_tool_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            self.create_provenance(out_dir)
            versions_path = out_dir / "tool_versions.json"
            before = versions_path.read_bytes()

            run_public_latitude_v2.validate_reuse(out_dir, self.context)

            self.assertEqual(versions_path.read_bytes(), before)

    def test_changed_context_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            self.create_provenance(out_dir)
            changed = {**self.context, "parameters": {"distance": ["0.10"]}}

            with self.assertRaisesRegex(SystemExit, "run context does not match"):
                run_public_latitude_v2.validate_reuse(out_dir, changed)

    def test_changed_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            self.create_provenance(out_dir)
            (out_dir / "metrics.csv").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "changed artifact metrics.csv"):
                run_public_latitude_v2.validate_reuse(out_dir, self.context)


if __name__ == "__main__":
    unittest.main()
