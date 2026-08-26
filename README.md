# JPEG XL vs DNG/PixelShift

Work in progress: a reproducible investigation into whether conservative JPEG XL
compression can be a practical archive strategy for high-resolution camera scans
of film.

The central question is not simply "is JPEG XL identical to DNG?" It is:

> Given a fixed storage budget, can a better-sampled image stored as conservative
> JPEG XL preserve more relevant information about a film original than a lower
> resolution raw capture?

Current working hypothesis:

- DNG or another lossless/raw-like master remains the safest per-pixel archive
  representation.
- For camera-scanned film, spatial sampling can matter more than preserving every
  last bit of scanner/camera precision.
- A 240 MP PixelShift capture stored as carefully tested JPEG XL may preserve
  more useful film structure than a 61 MP Bayer raw file at similar storage cost.
- This remains a hypothesis until repeated across public, non-private test
  material.

## Current Evidence

For a quick map of what each result can and cannot prove, start with
[FINDINGS.md](FINDINGS.md).

Public reproducible tests use FADGI/OpenDICE and Library of Congress TIFFs.
Private exploratory tests use local PixelShift camera scans. Together they show
the current pattern:

- JPEG XL lossless round-tripped the extracted 16-bit linear image data exactly.
- Lossless JPEG XL saved only modest space for the tested PixelShift2DNG files.
- Lossy JPEG XL errors were amplified by negative inversion and strong tonal
  edits.
- Public FADGI/OpenDICE and LOC tests make the stress pipeline reproducible,
  but they do not answer the PixelShift sampling question by themselves.
- In one FilmLab-based ProPhoto test, JPEG XL distance `0.05` reduced one DNG to
  about half its size while producing a much smaller post-inversion error than
  more aggressive settings.
- FilmLab 3.5.0 appeared to mishandle direct import of some lossy JXL color
  profiles, so measured FilmLab tests used `djxl` decoding followed by an
  ICC-preserved PNG bridge.

These results are not yet a universal archival recommendation.

## Repository Map

- [CONCLUSIONS.md](CONCLUSIONS.md): short executive summary and current
  practical recommendation
- [FINDINGS.md](FINDINGS.md): evidence map separating public FADGI/OpenDICE
  findings, private local scan findings, and still-pending claims
- [LICENSE](LICENSE): license for original project code and documentation
- [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md): rights notes for public test data
- [REPRODUCIBILITY.md](REPRODUCIBILITY.md): clean reproduction path for the
  public tests
- [RELATED_WORK.md](RELATED_WORK.md): prior-art and related-work framing
- [RESEARCH_PLAN.md](RESEARCH_PLAN.md): source-driven plan for the next test
  tracks
- [ARCHIVAL_VALUE_METRICS.md](ARCHIVAL_VALUE_METRICS.md): metric specification
  for the 61 MP raw versus 240 MP PixelShift JPEG XL break-even question
- [TEST_MATERIAL_STRATEGY.md](TEST_MATERIAL_STRATEGY.md): what input material is
  needed for credible negative/positive tests
- [NEXT_STEPS.md](NEXT_STEPS.md): remaining research and publication decisions
- [docs/publication-summary.md](docs/publication-summary.md): short shareable
  summary for public review
- [docs/sharing-plan.md](docs/sharing-plan.md): recommended public framing,
  current claims, and what must wait
- [METHODOLOGY.md](METHODOLOGY.md): planned and current test methodology
- [RESULTS.md](RESULTS.md): current result summary and interpretation
- [docs/public-latitude-v2.md](docs/public-latitude-v2.md): expanded public
  latitude stress test with density-based negative-print transforms
- [docs/adobe-dng-converter-jxl-dng-smoke-test.md](docs/adobe-dng-converter-jxl-dng-smoke-test.md):
  smoke test for rewriting PixelShift2DNG files as DNG 1.7 JPEG XL
- [LIMITATIONS.md](LIMITATIONS.md): what the tests do not prove
- [TESTDATA.md](TESTDATA.md): public test data sources and rights notes
- [docs/research-log.md](docs/research-log.md): project history and decisions
- [docs/publication-checklist.md](docs/publication-checklist.md): privacy and
  release checklist
- [docs/local-scan-workflow.md](docs/local-scan-workflow.md): private local
  workflow for adding scan folders under ignored `input/`
- [scripts/download_testdata.py](scripts/download_testdata.py): fetch public test
  targets and images
- [scripts/create_scan_manifest.py](scripts/create_scan_manifest.py): create
  private JSON/Markdown sidecars for local camera-scan folders, including
  ExifTool-based PixelShift grouping for raw-only imports
- [scripts/run_adobe_dng_jxl_batch.py](scripts/run_adobe_dng_jxl_batch.py):
  batch-run Adobe DNG Converter DNG/JPEG XL variants into
  `adc_jxl_dng/<level>/`
- [scripts/run_local_scan_study.py](scripts/run_local_scan_study.py):
  discover ignored local scan folders, run DNG/JXL verification where ADC
  candidates are complete, and write a local cross-scan index
- [scripts/run_storage_budget_index.py](scripts/run_storage_budget_index.py):
  summarize whether local single-shot raw and PixelShift 16 JXL candidates are
  actually size-comparable under the declared storage-budget definition
- [scripts/render_with_rawtherapee.py](scripts/render_with_rawtherapee.py):
  render RAW61, PS16, and ADC DNG/JXL candidates through one fixed RawTherapee
  profile as 16-bit TIFFs
- [scripts/register_raw61_to_ps16.py](scripts/register_raw61_to_ps16.py):
  scale and globally register a RAW61 render to its PS16 reference
- [scripts/run_raw61_loss_metrics.py](scripts/run_raw61_loss_metrics.py):
  measure the RAW61-vs-PS16 color/tone baseline consumed by the break-even
  matrix
- [scripts/run_structure_metrics.py](scripts/run_structure_metrics.py):
  measure high-pass structure retention for RAW61 and PS16 JXL candidates
- [scripts/run_rendered_ps16_jxl_matrix.py](scripts/run_rendered_ps16_jxl_matrix.py):
  encode rendered PS16 TIFF masters as standalone JPEG XL, decode them, and
  measure codec loss without relying on DNG/JXL application support
- [scripts/run_archival_break_even.py](scripts/run_archival_break_even.py):
  join size, DNG/JXL color-stress, metadata-risk, and external RAW61/structure
  metrics into a conservative break-even matrix
- [scripts/compare_dng_duplicate_candidates.py](scripts/compare_dng_duplicate_candidates.py):
  compare `-(1)` PixelShift2DNG duplicate candidates by decoded main-image data
- [scripts/audit_publication_safety.py](scripts/audit_publication_safety.py):
  local pre-publication safety audit
- [scripts/run_public_latitude_stress.py](scripts/run_public_latitude_stress.py):
  run reproducible JPEG XL stress tests on public TIFF crops
- [scripts/inspect_dng_jxl_color_path.py](scripts/inspect_dng_jxl_color_path.py):
  inspect embedded DNG/JXL headers and distinguish XYB from original-profile
  coding
- [scripts/run_dng_jxl_verification.py](scripts/run_dng_jxl_verification.py):
  compare source DNG files with Adobe DNG Converter DNG/JXL variants on matched
  active-crop windows, including DNG `OpcodeList2` handling
- [scripts/make_public_crop_panels.py](scripts/make_public_crop_panels.py):
  create reference/candidate/diff panels from public stress-test output
- [src/jxl_archive_test.py](src/jxl_archive_test.py): helper CLI for comparing
  rendered image states and JPEG XL encode/decode tests

## Quick Start

Install the helper package:

```powershell
python -m pip install -e ".[public-tests]"
```

Use the bundled Git LFS test data, or download public test data:

```powershell
git lfs install
git lfs pull

python scripts\download_testdata.py --include-loc --loc-count 3
```

Run a publication safety audit:

```powershell
python scripts\audit_publication_safety.py
```

Run all lightweight publication-readiness checks:

```powershell
python scripts\check_publication_ready.py
```

Run the current public latitude-stress v2 pipeline:

```powershell
python scripts\run_public_latitude_v2.py --publish-figures
```

Run the private local scan-study queue for ignored folders under `input/`:

```powershell
python scripts\run_local_scan_study.py --dry-run
python scripts\run_local_scan_study.py
python scripts\run_storage_budget_index.py
python scripts\run_archival_break_even.py --write-templates
```

For the actual break-even search, generate and analyze additional JPEG XL
distances such as `d015`, `d020`, `d030`, and `d050`; `d020` maps to Adobe DNG
Converter distance `0.20`.

See [docs/local-scan-workflow.md](docs/local-scan-workflow.md) before adding new
private negatives.

For a fuller clean-clone path, see [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

Compare already-rendered files:

```powershell
jxl-archive-test compare-rendered "D:\scan-tests\reference.tif" `
  "D:\scan-tests\candidate.tif" `
  --name candidate `
  --out-dir "D:\scan-tests\compare_results"
```

Run JPEG XL encode/decode tests from one reference TIFF:

```powershell
jxl-archive-test encode-test "D:\scan-tests\reference.tif" `
  --out-dir "D:\scan-tests\jxl_results"
```

Render DNG files using a command template:

```powershell
jxl-archive-test render-dng "D:\scan-tests\reference.dng" `
  "D:\scan-tests\candidate.dng" `
  --render-command 'darktable-cli "{input}" "{output}"' `
  --out-dir "D:\scan-tests\rendered_dngs"
```

The important rule is to compare the same rendered image state. Comparing a DNG
container directly with a TIFF, PNG, or JXL file usually answers the wrong
question.

## Status

This repo is close to a public-review state, but it is still a research project,
not an archival recommendation. Private scans and generated local outputs are
intentionally ignored by Git. Public samples should be downloaded or stored under
`testdata/` with source sidecars and SHA-256 hashes.

For the shortest current interpretation, start with
[CONCLUSIONS.md](CONCLUSIONS.md).
