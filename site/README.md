# Verified report

The [public report](https://hsnilsson.github.io/bayer-raw-vs-pixel-shift-jpeg-xl/) was first approved and published on 2026-09-17. Set up the environment using the [reproduction instructions](../REPRODUCIBILITY.md), then serve the repository with `.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1` and open `/site/index.html`. The RGB16 viewer uses HTTP fetch and gzip `DecompressionStream` support.

`data/release.json` binds the current report, measurements and all evidence assets, and identifies the source repository and fixed version tag. The HTML is generated from that release. Run `.\.venv\Scripts\python.exe scripts/check_verified_release.py` and `.\.venv\Scripts\python.exe scripts/check_report_site.py` before delivery or publication.

The release builder copies the repository's canonical reproduction guide into `data/reproduction.md`; the release check verifies that both copies match. See the [review record](data/review-notes.md) and [remaining research questions](../LIMITATIONS.md).
