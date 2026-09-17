"""Run the frozen measurement engine with stable, resumable preview exports.

Only the atomic PNG output boundary is composed with a reuse policy. Existing
PNG bytes are kept when decoded pixels and all metadata/profile bytes match,
apart from the ICC creation timestamp. This prevents a partial restart from
invalidating completed measurements merely by refreshing reference previews.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import rebuild_verified_report as engine
from preview_cache import preserve_equivalent_png


def main():
    engine.atomic_bytes = preserve_equivalent_png(engine.atomic_bytes)
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
