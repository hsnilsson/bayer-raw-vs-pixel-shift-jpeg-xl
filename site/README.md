# Validated local report

Serve the repository with `python -m http.server 8765 --bind 127.0.0.1` and open `/site/index.html`. The RGB16 viewer requires HTTP fetch and a modern browser with gzip `DecompressionStream` support.

`data/release.json` binds the current report, measurements and all evidence assets. The HTML is generated from that release; do not edit tables or viewer labels independently. Run `python scripts/check_verified_release.py` and `python scripts/check_report_site.py` before delivery or publication.

This report awaits owner review. No deployment is included in the repair. See [reproduction](../REPRODUCIBILITY.md) and [limitations](../LIMITATIONS.md).
