from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compare_dng_duplicate_candidates as duplicate_compare  # noqa: E402


def write_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dng")


class CompareDngDuplicateCandidatesTests(unittest.TestCase):
    def test_canonical_stem_for_duplicate(self) -> None:
        self.assertEqual(
            duplicate_compare.canonical_stem_for_duplicate("DSC1000-DSC1015-(1)"),
            "DSC1000-DSC1015",
        )
        self.assertIsNone(duplicate_compare.canonical_stem_for_duplicate("DSC1000-DSC1015"))

    def test_discover_duplicate_pairs_matches_root_canonical(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_file(root / "DSC1000-DSC1015.dng")
        write_file(root / "_review" / "duplicate_dng_candidates" / "DSC1000-DSC1015-(1).dng")
        write_file(root / "_review" / "duplicate_dng_candidates" / "DSC2000-DSC2015-(1).dng")

        pairs = duplicate_compare.discover_duplicate_pairs(root)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].canonical.name, "DSC1000-DSC1015.dng")
        self.assertEqual(pairs[0].duplicate.name, "DSC1000-DSC1015-(1).dng")


if __name__ == "__main__":
    unittest.main()
