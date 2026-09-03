from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_opendice_sample as opendice  # noqa: E402


class OpenDiceSampleTests(unittest.TestCase):
    def test_material_11_failure_signature_is_exact(self) -> None:
        self.assertEqual(
            opendice.MATERIAL_11_FAILURE,
            "Unable to resolve the name 'handles.material'.",
        )

    def test_build_command_matches_official_parameter_order(self) -> None:
        command = opendice.build_command(
            Path("OpenDICECommand.exe"),
            Path("Config_materials2023.txt"),
            11,
            4,
            Path("Negative 35mm_2.tif"),
            12,
            Path("Profile_35mm_Negative2.txt"),
            True,
        )

        expected_image = str(Path("Negative 35mm_2.tif").resolve())
        self.assertEqual(command[2:5], ["11", "4", expected_image])
        self.assertEqual(command[5], "12")
        self.assertEqual(command[-1], "-e")

    def test_luminance_only_command_omits_export_flag(self) -> None:
        command = opendice.build_command(
            Path("OpenDICECommand.exe"),
            Path("Config_materials2023.txt"),
            11,
            4,
            Path("target.tif"),
            12,
            Path("profile.txt"),
            False,
        )

        self.assertNotIn("-e", command)


if __name__ == "__main__":
    unittest.main()
