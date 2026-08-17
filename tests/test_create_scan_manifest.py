from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import create_scan_manifest  # noqa: E402


def write_file(path: Path, size: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(range(size)))


class CreateScanManifestTests(unittest.TestCase):
    def make_scan_root(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "_DSC1000.ARW")
        write_file(root / "_DSC1000.JPG")
        for number in range(1001, 1005):
            write_file(root / f"_DSC{number}.ARW")
        for number in range(1005, 1021):
            write_file(root / f"_DSC{number}.ARW")
        write_file(root / "_DSC1001-_DSC1004.dng")
        write_file(root / "_DSC1005-_DSC1020.dng")
        write_file(root / "adc_jxl_dng" / "lossless" / "_DSC1005-_DSC1020.dng")
        write_file(root / "adc_jxl_dng" / "d005" / "_DSC1005-_DSC1020.dng")
        return root

    def test_manifest_groups_single_ps4_ps16_and_adc_outputs(self) -> None:
        root = self.make_scan_root()

        manifest = create_scan_manifest.build_manifest(root, use_exiftool=False)

        self.assertEqual(manifest["totals"]["files"], 26)
        self.assertEqual(len(manifest["capture_sets"]), 1)
        capture = manifest["capture_sets"][0]
        self.assertEqual(capture["single_raw"], "_DSC1000.ARW")
        self.assertEqual(capture["pixelshift4_dng"], "_DSC1001-_DSC1004.dng")
        self.assertEqual(capture["pixelshift16_dng"], "_DSC1005-_DSC1020.dng")
        self.assertEqual(capture["adc_levels_for_pixelshift16"], ["d005", "lossless"])
        self.assertEqual(capture["storage_budget_role"], "primary_candidate")

        ps16 = next(item for item in manifest["sequences"] if item["mode"] == "pixelshift16")
        self.assertEqual(ps16["raw_files_present"], 16)
        self.assertEqual(ps16["raw_files_expected"], 16)
        self.assertEqual(ps16["missing_raw_files"], [])

    def test_adc_outputs_are_marked_regeneratable(self) -> None:
        root = self.make_scan_root()

        manifest = create_scan_manifest.build_manifest(root, use_exiftool=False)

        adc_entries = [
            entry for entry in manifest["files"]
            if entry["role"] == "adc_dng_jxl_candidate"
        ]
        self.assertEqual(len(adc_entries), 2)
        self.assertTrue(all(entry["archive_action"] == "regenerate" for entry in adc_entries))
        self.assertTrue(
            all(
                entry["regeneration"] == "from_pixelshift_dng_and_adobe_dng_converter"
                for entry in adc_entries
            )
        )

    def test_hash_option_adds_sha256(self) -> None:
        root = self.make_scan_root()

        manifest = create_scan_manifest.build_manifest(root, hash_files=True, use_exiftool=False)

        arw = next(entry for entry in manifest["files"] if entry["path"] == "_DSC1000.ARW")
        self.assertEqual(arw["sha256"], "ae4b3280e56e2faf83f414a6e3dabe9d5fbe18976544c05fed121accb85b53fc")

    def test_write_outputs_refuses_to_overwrite_without_force(self) -> None:
        root = self.make_scan_root()
        manifest = create_scan_manifest.build_manifest(root, use_exiftool=False)
        out_json = root / "scan_manifest.json"
        out_md = root / "scan_manifest.md"
        create_scan_manifest.write_outputs(manifest, out_json, out_md, force=False)

        with self.assertRaises(FileExistsError):
            create_scan_manifest.write_outputs(manifest, out_json, out_md, force=False)

        create_scan_manifest.write_outputs(manifest, out_json, out_md, force=True)
        self.assertIn("Scan Manifest", out_md.read_text(encoding="utf-8"))

    def test_output_files_can_be_excluded_from_manifest(self) -> None:
        root = self.make_scan_root()
        out_json = root / "scan_manifest.json"
        out_md = root / "scan_manifest.md"
        write_file(out_json)
        write_file(out_md)

        manifest = create_scan_manifest.build_manifest(
            root,
            exclude_paths={out_json, out_md},
            use_exiftool=False,
        )

        paths = {entry["path"] for entry in manifest["files"]}
        self.assertNotIn("scan_manifest.json", paths)
        self.assertNotIn("scan_manifest.md", paths)

    def test_pixelshift_info_parser_accepts_sony_exiftool_value(self) -> None:
        parsed = create_scan_manifest.parse_pixelshift_info("Group 17163427, Shot 3/4 (0x3)")

        self.assertEqual(parsed, ("17163427", 3, 4))

    def test_raw_pixelshift_groups_can_drive_raw_only_capture_sets(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "_DSC2000.ARW")
        write_file(root / "_DSC2000.JPG")
        for number in range(2001, 2005):
            write_file(root / f"_DSC{number}.ARW")
        for number in range(2005, 2021):
            write_file(root / f"_DSC{number}.ARW")
        for number in range(2021, 2037):
            write_file(root / f"_DSC{number}.ARW")

        rows = []
        for shot, number in enumerate(range(2001, 2005), start=1):
            rows.append(
                {
                    "SourceFile": str(root / f"_DSC{number}.ARW"),
                    "FileName": f"_DSC{number}.ARW",
                    "PixelShiftInfo": f"Group 11, Shot {shot}/4 (0x{shot:x})",
                }
            )
        for shot, number in enumerate(range(2005, 2021), start=1):
            rows.append(
                {
                    "SourceFile": str(root / f"_DSC{number}.ARW"),
                    "FileName": f"_DSC{number}.ARW",
                    "PixelShiftInfo": f"Group 12, Shot {shot}/16 (0x{shot:x})",
                }
            )
        for shot, number in enumerate(range(2021, 2037), start=1):
            rows.append(
                {
                    "SourceFile": str(root / f"_DSC{number}.ARW"),
                    "FileName": f"_DSC{number}.ARW",
                    "PixelShiftInfo": f"Group 13, Shot {shot}/16 (0x{shot:x})",
                }
            )

        groups = create_scan_manifest.raw_pixelshift_groups_from_rows(rows, root)
        capture_sets = create_scan_manifest.build_capture_sets(root, [], groups)

        self.assertEqual([group.mode for group in groups], ["pixelshift4", "pixelshift16", "pixelshift16"])
        self.assertEqual(groups[0].raw_files_present, 4)
        self.assertEqual(groups[1].missing_shots, [])
        self.assertEqual(capture_sets[0].single_raw, "_DSC2000.ARW")
        self.assertEqual(capture_sets[0].pixelshift4_raw_group, "11")
        self.assertEqual(capture_sets[0].pixelshift16_raw_group, "12")
        self.assertEqual(capture_sets[0].single_raw_kind, "normal_single_raw")
        self.assertEqual(capture_sets[0].storage_budget_role, "primary_candidate")
        self.assertIsNone(capture_sets[1].single_raw)
        self.assertEqual(capture_sets[1].pixelshift16_raw_group, "13")
        self.assertEqual(capture_sets[1].storage_budget_role, "unpaired_secondary")

    def test_pixelshift_one_of_one_single_is_secondary_for_storage_budget(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "_DSC3000.ARW")
        for number in range(3001, 3005):
            write_file(root / f"_DSC{number}.ARW")
        for number in range(3005, 3021):
            write_file(root / f"_DSC{number}.ARW")

        rows = [
            {
                "SourceFile": str(root / "_DSC3000.ARW"),
                "FileName": "_DSC3000.ARW",
                "PixelShiftInfo": "Group 20, Shot 1/1 (0x1)",
            }
        ]
        for shot, number in enumerate(range(3001, 3005), start=1):
            rows.append(
                {
                    "SourceFile": str(root / f"_DSC{number}.ARW"),
                    "FileName": f"_DSC{number}.ARW",
                    "PixelShiftInfo": f"Group 21, Shot {shot}/4 (0x{shot:x})",
                }
            )
        for shot, number in enumerate(range(3005, 3021), start=1):
            rows.append(
                {
                    "SourceFile": str(root / f"_DSC{number}.ARW"),
                    "FileName": f"_DSC{number}.ARW",
                    "PixelShiftInfo": f"Group 22, Shot {shot}/16 (0x{shot:x})",
                }
            )

        groups = create_scan_manifest.raw_pixelshift_groups_from_rows(rows, root)
        capture_sets = create_scan_manifest.build_capture_sets(root, [], groups)

        self.assertEqual(len(capture_sets), 1)
        self.assertEqual(capture_sets[0].single_raw, "_DSC3000.ARW")
        self.assertEqual(capture_sets[0].single_raw_kind, "pixelshift1_single_raw")
        self.assertEqual(capture_sets[0].storage_budget_role, "secondary_only")
        self.assertIn("exclude from primary", capture_sets[0].notes)


if __name__ == "__main__":
    unittest.main()
