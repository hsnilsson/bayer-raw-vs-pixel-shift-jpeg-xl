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

        manifest = create_scan_manifest.build_manifest(root)

        self.assertEqual(manifest["totals"]["files"], 26)
        self.assertEqual(len(manifest["capture_sets"]), 1)
        capture = manifest["capture_sets"][0]
        self.assertEqual(capture["single_raw"], "_DSC1000.ARW")
        self.assertEqual(capture["pixelshift4_dng"], "_DSC1001-_DSC1004.dng")
        self.assertEqual(capture["pixelshift16_dng"], "_DSC1005-_DSC1020.dng")
        self.assertEqual(capture["adc_levels_for_pixelshift16"], ["d005", "lossless"])

        ps16 = next(item for item in manifest["sequences"] if item["mode"] == "pixelshift16")
        self.assertEqual(ps16["raw_files_present"], 16)
        self.assertEqual(ps16["raw_files_expected"], 16)
        self.assertEqual(ps16["missing_raw_files"], [])

    def test_adc_outputs_are_marked_regeneratable(self) -> None:
        root = self.make_scan_root()

        manifest = create_scan_manifest.build_manifest(root)

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

        manifest = create_scan_manifest.build_manifest(root, hash_files=True)

        arw = next(entry for entry in manifest["files"] if entry["path"] == "_DSC1000.ARW")
        self.assertEqual(arw["sha256"], "ae4b3280e56e2faf83f414a6e3dabe9d5fbe18976544c05fed121accb85b53fc")

    def test_write_outputs_refuses_to_overwrite_without_force(self) -> None:
        root = self.make_scan_root()
        manifest = create_scan_manifest.build_manifest(root)
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
        )

        paths = {entry["path"] for entry in manifest["files"]}
        self.assertNotIn("scan_manifest.json", paths)
        self.assertNotIn("scan_manifest.md", paths)


if __name__ == "__main__":
    unittest.main()
