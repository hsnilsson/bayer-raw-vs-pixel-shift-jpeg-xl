from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_metadata_roundtrip import compare


class MetadataDiffTests(unittest.TestCase):
    def test_reports_missing_changed_and_added_fields_without_values(self):
        source = {"IFD0:Artist": "private name", "XMP-dc:Subject": ["private keyword"], "IFD0:Make": "camera"}
        candidate = {"IFD0:Artist": "private name", "IFD0:Make": "different", "XMP-xmp:CreatorTool": "tool"}
        result = compare(source, candidate)
        self.assertEqual({r["field"]: r["status"] for r in result["fields"]}, {
            "IFD0:Artist": "preserved", "XMP-dc:Subject": "missing", "IFD0:Make": "changed",
            "XMP-xmp:CreatorTool": "added"})
        self.assertNotIn("private", str(result))
        self.assertEqual(result["counts"], {"preserved": 1, "changed": 1, "added": 1, "missing": 1})

    def test_does_not_claim_preservation_for_fields_absent_from_both_files(self):
        self.assertEqual(compare({}, {}), {"counts": {}, "fields": []})
        self.assertEqual(compare({"XMP-dc:Subject": ["a", "b"]}, {"XMP-dc:Subject": ["a"]})["fields"][0]["status"], "changed")


if __name__ == "__main__":
    unittest.main()
