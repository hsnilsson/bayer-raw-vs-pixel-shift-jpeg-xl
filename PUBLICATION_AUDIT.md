# Publication Audit

This audit is for opening the repository publicly. It does not rewrite Git
history; large historical objects can be handled separately if needed.

## Current State

- The tracked repository passes the publication safety audit with no blocking
  findings.
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
  report uses standalone JXL. They document why ADC DNG/JXL is not yet the main
  candidate.
- `scripts/generate_break_even_report_site.py` and `site/`: keep as the current
  publication path.

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

## Needs Decision Before Public Release

- Whether any full-size source scans should ever be published through Git LFS.
  The current default is selected small derived panels and context thumbnails
  only.
- Whether `site/` should be treated as live now, or as a draft until the first
  public writeup is frozen.
- Whether old narrative pages should remain as documentation, or whether the
  public site should expose only `README`, `FINDINGS`, `RESULTS`,
  `METHODOLOGY`, `LIMITATIONS`, and `RELATED_WORK`.

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
