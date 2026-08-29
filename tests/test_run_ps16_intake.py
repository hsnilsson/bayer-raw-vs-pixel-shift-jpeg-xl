from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_ps16_intake  # noqa: E402


class RunPs16IntakeTests(unittest.TestCase):
    def test_expected_dng_name_uses_first_and_last_stem(self) -> None:
        self.assertEqual(
            run_ps16_intake.expected_dng_name("FRAME0001.ARW", "FRAME0016.ARW"),
            "FRAME0001-FRAME0016.dng",
        )

    def test_adc_lossy_command_maps_level_to_distance(self) -> None:
        command = run_ps16_intake.adc_command(
            Path("adc.exe"), Path("source.dng"), Path("out"), "d022", 7
        )
        self.assertEqual(
            command,
            [
                "adc.exe",
                "-lossy",
                "-jxl_effort",
                "7",
                "-jxl_distance",
                "0.22",
                "-d",
                "out",
                "source.dng",
            ],
        )

    def test_adc_lossless_command(self) -> None:
        command = run_ps16_intake.adc_command(
            Path("adc.exe"), Path("source.dng"), Path("out"), "lossless", 7
        )
        self.assertEqual(command, ["adc.exe", "-losslessJXL", "-d", "out", "source.dng"])


if __name__ == "__main__":
    unittest.main()
