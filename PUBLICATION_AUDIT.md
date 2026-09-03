# Publication Audit

This audit is for opening the repository publicly. It does not rewrite Git
history; large historical objects can be handled separately if needed.

## Current State

- The tracked repository passes the publication safety audit with no blocking
  findings or warnings. Expected Git LFS notices are informational.
- Large public TIFF test inputs are intentionally tracked through Git LFS.
- Full-size local scans and generated outputs are ignored by Git.
- The current public site target is `site/`.
- The local full report is generated under `results/break_even_report/`.

## Safe To Keep

- `testdata/fadgi_opendice/**`: public FADGI/OpenDICE material with source
  sidecars; large files are LFS-tracked.
- `testdata/library_of_congress/highsmith/**`: public Library of Congress
  material with source sidecars; large files are LFS-tracked.
- `docs/figures/public-latitude-v2/**`: current public method figures.
- `docs/figures/public-smoke-test/**`: older public figures, still referenced
  by the archived smoke-test page.
- `docs/archive/public-smoke-test.md`: useful project history; keep unless the
  public site becomes intentionally very minimal.
- `scripts/run_adobe_dng_jxl_batch.py`, `scripts/run_dng_jxl_verification.py`,
  and `scripts/inspect_dng_jxl_color_path.py`: keep even though the current
  report uses standalone JXL. They document why ADC DNG/JXL was excluded from
  the core candidate comparison.
- `scripts/generate_break_even_report_site.py` and `site/`: keep as the current
  publication path.

Removed before publication because they contradicted or distracted from the
measured study:

- the separate production/intake pipeline that treated ADC DNG/JXL as an
  archive output;
- the redundant one-shot ADC intake runner; and
- the unfinished Sony Imaging Edge merge-control track.

## Can Be Removed Locally

These directories are ignored and do not affect the public repository, but they
consume local disk:

- old generated `outputs/` candidates and decoded intermediates after the
  current result CSVs and selected panels have been preserved.

Do not remove `input/` or source scan folders unless the source files are backed
up elsewhere.

Already cleaned locally:

- `trash/` has been emptied.
- stale Kodak Gold `d030_auto-detail_identity.png` and `d030_center_identity.png`
  review panels are excluded from the site build and can be regenerated if
  needed.

## Publication Decisions

- `site/` is the current publishable report artifact.
- Publish selected derived review crops, context thumbnails, and public test
  figures. Do not publish full-size private source scans through Git LFS.
- Keep historical narrative under `docs/archive/`; current claims belong in
  `README`, `FINDINGS`, `RESULTS`, `CONCLUSIONS`, `METHODOLOGY`, and
  `LIMITATIONS`.

## Drift Found

- Several documents still used older language saying local Kodak material could
  not be shared. The main public-facing documents now describe it as local
  material whose selected derived panels can be owner-approved for publication.
- Older documents emphasized `d=0.03`/`d=0.05` from the ADC and public stress
  tracks. The standalone PS16 JXL break-even sweep now has finer levels:
  `d020`, `d022`, `d025`, `d028`, and `d030`.
- The main question has not drifted. The project is still about whether more
  spatial sampling plus conservative JPEG XL can beat lower-resolution RAW at a
  fixed storage budget.
- The largest remaining methodological risk is still the RAW61-vs-PS16
  render/profile baseline. It should stay visible in public conclusions.

## Recommended Public Opening

Open the repository publicly with:

- tracked code, docs, source sidecars, and public LFS test data;
- the GitHub Pages workflow already present;
- selected derived Kodak review panels and full-frame context thumbnails under
  `site/assets/`;
- no full-size local `input/`, `outputs/`, `results/`, or `trash/` directories.
