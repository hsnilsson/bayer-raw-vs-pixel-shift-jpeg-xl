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

- `trash/`: old local scan/output material. It is currently the clearest local
  cleanup candidate.
- stale review panels in the current Kodak Gold review-panel output folder:
  `d030_auto-detail_identity.png` and `d030_center_identity.png`.
- old generated `outputs/` candidates and decoded intermediates after the
  current result CSVs and selected panels have been preserved.

Do not remove `input/` or source scan folders unless the source files are backed
up elsewhere.

## Needs Decision Before Public Release

- Whether to publish only selected derived panels or also publish full-size
  source scans through Git LFS.
- Whether `site/` should contain the generated full report now, or remain a
  placeholder until the first public writeup is frozen.
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
- selected derived Kodak review panels only after copying them into `site/` or
  another documented public asset folder;
- no full-size local `input/`, `outputs/`, `results/`, or `trash/` directories.
