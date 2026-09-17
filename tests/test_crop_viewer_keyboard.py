"""Exercise the viewer's actual keyboard handlers with lightweight DOM controls."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CropViewerKeyboardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for viewer JavaScript tests")
    def test_navigation_dropdown_selection_and_overlay(self):
        result = subprocess.run(["node", str(ROOT / "tests/crop_viewer_keyboard.cjs")],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
