from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_report_site import check_site  # noqa: E402


class ReportSiteLinkTests(unittest.TestCase):
    def test_published_site_references_resolve(self) -> None:
        checked, errors = check_site(ROOT / "site")
        self.assertGreater(checked, 0)
        self.assertEqual(errors, [])

    def test_rejects_existing_files_outside_uploaded_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "plot.svg").write_text("<svg/>", encoding="utf-8")
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text('<img src="../plot.svg">', encoding="utf-8")
            _, errors = check_site(site)
            self.assertEqual(len(errors), 1)
            self.assertIn("outside the published site", errors[0])

    def test_checks_dynamic_assets_anchors_and_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "plot.svg").write_text("<svg/>", encoding="utf-8")
            (site / "index.html").write_text('''
                <h2 id="results">Results</h2><a href="#results">OK</a>
                <img src="plot.svg?version=1"><a href="https://example.com">External</a>
                <a href="#absent">Missing section</a><img src="Plot.svg">
                <img data-highlight="missing-highlight.png">
                <script type="application/json">[{"sources":{"identity":"missing.rgb16le"}}]</script>
                <script>const files = {"reference":"missing-overview.png"};</script>
            ''', encoding="utf-8")
            checked, errors = check_site(site)
            self.assertEqual(checked, 7)
            self.assertEqual(len(errors), 5)
            for reference in ("#absent", "Plot.svg", "missing-highlight.png", "missing.rgb16le", "missing-overview.png"):
                self.assertTrue(any(reference in error for error in errors), reference)

    def test_resolves_nested_pages_encoded_paths_and_parent_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "nested").mkdir()
            (site / "plot one.svg").write_text("<svg/>", encoding="utf-8")
            (site / "index.html").write_text('<a href="nested/#result">Nested</a>', encoding="utf-8")
            (site / "nested/index.html").write_text(
                '<h2 id="result">OK</h2><img src="../plot%20one.svg"><a href="../">Home</a>',
                encoding="utf-8",
            )
            self.assertEqual(check_site(site), (3, []))

    def test_empty_site_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(check_site(Path(temp)), (0, ["missing site/index.html"]))


if __name__ == "__main__":
    unittest.main()
