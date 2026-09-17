# Publication audit and local retention

The corrected report under `site/` is prepared for owner review. Publication requires a separate instruction; pushing site changes to `main` triggers the Pages workflow. The machine-assisted check record is [site/data/review-notes.md](site/data/review-notes.md).

## Public release boundary

- Publish the existing approved native crops, reduced context maps, public test panels, sanitized CSV/JSON evidence, code and method documentation.
- Keep private full scans, source RAW/DNG files, retained TIFF/PPM renders, full encoded candidates, local paths and photographic identity metadata outside the public release.
- Public test TIFFs under `testdata/` retain their source sidecars and Git LFS tracking. See [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).
- `site/data/release.json` binds the current evidence and assets. The site build receipt binds the HTML and standalone crop redirects. Historical figures and numerical records outside that release do not support current claims.

## Checks

Run `python scripts/audit_publication_safety.py`, `python scripts/check_publication_ready.py`, `python scripts/check_verified_release.py` and `python scripts/check_report_site.py` before release. The release gate rejects local absolute paths, missing or changed evidence, stale code/assets, incorrect cohorts and relaxed byte budgets. The publication audit checks Git-visible files for private metadata and unexpected large binaries.

The automated checks complement owner review; they do not grant permission to publish additional private material. This repair reuses approved selections and withdraws unsupported DNG display-color and archive-value verdicts.

## Retain for private reproduction

Keep the original captures, retained neutral renders, original and metadata-repaired JPEG XL candidates, source inventories, content checkpoints and the `results/verified_report/viewer-pixels` cache. These may be ignored by Git while remaining necessary for later audits and efficient restart. Ignored does not mean disposable.

The documented finalizer packs generated crop transport and moves its uncompressed originals to that cache. `scripts/prune_superseded_site_assets.py` can remove only superseded files inside this checkout's `site/assets` after validating the replacement. It does not authorize deleting archive inputs, retained renders, candidates or historical results. Review any broader cleanup separately.

No pre-existing Windows Temp file is a required input to the corrected pipeline. New work uses the explicitly selected persistent scratch directory.
