from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import serve_crop_selection as crop_server  # noqa: E402


class CropSelectionServerTests(unittest.TestCase):
    def guide(self, root: Path) -> crop_server.Guide:
        image = root / "set" / "frame" / "ps16_guide.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"png")
        metadata = image.with_suffix(".json")
        metadata.write_text("{}", encoding="utf-8")
        return crop_server.Guide(
            key="set|frame",
            scan_set="set",
            set_id="frame",
            image_path=image,
            metadata_path=metadata,
            display_width=900,
            display_height=600,
            source_width=18000,
            source_height=12000,
            offset_x=0,
            offset_y=42,
        )

    def test_marker_is_mapped_to_centered_source_crop(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            guide = self.guide(Path(directory))
            self.assertEqual(crop_server.crop_from_marker(guide, [450, 300], 768), [8616, 5616, 768, 768])

    def test_edge_marker_clamps_crop_inside_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            guide = self.guide(Path(directory))
            self.assertEqual(crop_server.crop_from_marker(guide, [0, 0], 768), [0, 0, 768, 768])
            self.assertEqual(crop_server.crop_from_marker(guide, [900, 600], 768), [17232, 11232, 768, 768])

    def test_plan_keeps_empty_cases_and_numbers_markers(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            guide = self.guide(Path(directory))
            plan = crop_server.build_crop_plan([guide], {guide.key: [[100, 200], [300, 400]]}, 512)
            crops = plan["cases"][guide.key]["crops"]
            self.assertEqual([crop["name"] for crop in crops], ["manual-01", "manual-02"])
            self.assertEqual(crops[0]["marker_display"], [100, 200])

    def test_plan_rejects_marker_outside_display(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            guide = self.guide(Path(directory))
            with self.assertRaisesRegex(ValueError, "outside image"):
                crop_server.build_crop_plan([guide], {guide.key: [[901, 10]]}, 768)

    def test_existing_plan_loads_marker_positions(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            guide = self.guide(root)
            output = root / "crop_plan.json"
            output.write_text(
                json.dumps({"crop_size": 640, "cases": {guide.key: {"crops": [{"marker_display": [12, 34]}]}}}),
                encoding="utf-8",
            )
            crop_size, markers = crop_server.load_existing_markers(output, [guide])
            self.assertEqual(crop_size, 640)
            self.assertEqual(markers[guide.key], [[12, 34]])


if __name__ == "__main__":
    unittest.main()
