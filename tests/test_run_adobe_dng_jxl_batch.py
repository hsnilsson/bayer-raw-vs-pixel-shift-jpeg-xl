from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_adobe_dng_jxl_batch as adc_batch  # noqa: E402


def write_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dng")


class RunAdobeDngJxlBatchTests(unittest.TestCase):
    def test_source_dngs_only_reads_scan_root(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "DSC1000-DSC1015.dng")
        write_file(root / "_review" / "duplicate_dng_candidates" / "DSC1000-DSC1015-(1).dng")
        write_file(root / "adc_jxl_dng" / "lossless" / "DSC1000-DSC1015.dng")

        sources = adc_batch.source_dngs(root)

        self.assertEqual([source.name for source in sources], ["DSC1000-DSC1015.dng"])

    def test_source_dngs_reads_nested_source_folder(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "dng" / "DSC1000-DSC1015.dng")
        write_file(root / "adc_jxl_dng" / "d020" / "DSC1000-DSC1015.dng")

        sources = adc_batch.source_dngs(root)

        self.assertEqual([source.relative_to(root).as_posix() for source in sources], ["dng/DSC1000-DSC1015.dng"])

    def test_source_dngs_can_filter_requested_stems(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "DSC1000-DSC1015.dng")
        write_file(root / "DSC2000-DSC2015.dng")

        sources = adc_batch.source_dngs(root, ["DSC2000-DSC2015"])

        self.assertEqual([source.name for source in sources], ["DSC2000-DSC2015.dng"])

    def test_source_dngs_rejects_missing_requested_source(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)

        with self.assertRaisesRegex(FileNotFoundError, "requested source DNG"):
            adc_batch.source_dngs(root, ["missing"])

    def test_lossless_command_uses_lossless_jxl_flag(self) -> None:
        command = adc_batch.command_for_conversion(
            Path("Adobe DNG Converter.exe"),
            "lossless",
            Path("source.dng"),
            Path("out"),
            effort=7,
        )

        self.assertIn("-losslessJXL", command)
        self.assertNotIn("-lossy", command)
        self.assertEqual(command[-2:], ["out", "source.dng"])

    def test_lossy_command_uses_distance_and_effort(self) -> None:
        command = adc_batch.command_for_conversion(
            Path("Adobe DNG Converter.exe"),
            "d020",
            Path("source.dng"),
            Path("out"),
            effort=8,
        )

        self.assertIn("-lossy", command)
        self.assertIn("-jxl_effort", command)
        self.assertIn("8", command)
        self.assertIn("-jxl_distance", command)
        self.assertIn("0.20", command)

    def test_dry_run_does_not_write_manifest(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        adc = root / "Adobe DNG Converter.exe"
        write_file(adc)
        write_file(root / "source.dng")

        result = adc_batch.main([str(root), "--adc", str(adc), "--dry-run"])

        self.assertEqual(result, 0)
        self.assertFalse((root / "adc_jxl_dng" / "run_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
