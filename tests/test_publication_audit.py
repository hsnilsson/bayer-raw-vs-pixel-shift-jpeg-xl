from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_publication_safety as audit  # noqa: E402


class PublicationAuditPatternTests(unittest.TestCase):
    def labels_for(self, text: str) -> list[str]:
        return [label for label, pattern in audit.SECRET_PATTERNS if pattern.search(text)]

    def test_public_camera_frame_id_is_not_treated_as_identity(self) -> None:
        self.assertEqual(self.labels_for('{"frame": "_DSC6577"}'), [])

    def test_javascript_serial_variable_is_not_treated_as_camera_metadata(self) -> None:
        self.assertEqual(self.labels_for("const serial = ++loadSerial;"), [])

    def test_json_serial_number_is_treated_as_identity_metadata(self) -> None:
        field = "Serial" + "Number"
        self.assertIn(
            "metadata_identity_field",
            self.labels_for(f'{{"{field}": "redacted-value"}}'),
        )

    def test_exif_owner_name_is_treated_as_identity_metadata(self) -> None:
        field = "Owner" + " Name"
        self.assertIn(
            "metadata_identity_field",
            self.labels_for(f"{field}: redacted-value"),
        )


if __name__ == "__main__":
    unittest.main()
