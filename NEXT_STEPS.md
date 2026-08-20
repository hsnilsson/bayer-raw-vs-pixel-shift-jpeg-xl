# Next Steps

This file is the short execution queue. The rationale is in
[RESEARCH_PLAN.md](RESEARCH_PLAN.md), input-material requirements are in
[TEST_MATERIAL_STRATEGY.md](TEST_MATERIAL_STRATEGY.md), the evidence map is in
[FINDINGS.md](FINDINGS.md), and the prior-art framing is in
[RELATED_WORK.md](RELATED_WORK.md).

## Current Priority

Turn the project from "JPEG XL stress test" into a stronger storage-budget
study:

```text
61 MP single-shot raw/DNG
versus
240 MP PixelShift 16 stored as conservative JPEG XL
within the predeclared storage tolerance in `RESEARCH_PLAN.md`
```

The newest practical path to test is Adobe DNG Converter output:

```text
PixelShift2DNG DNG -> Adobe DNG Converter -> DNG 1.7 JPEG XL
```

## Sole-Master Blocker For Lossy ADC JXL DNG

Lossy Adobe DNG Converter JXL DNG must remain an experimental candidate, not an
only-master recommendation, until every item below passes:

- render the source PixelShift2DNG and ADC candidate through the same trusted
  pipeline and register the resulting image areas before comparing them
- explain and test the observed stored-image changes in crop, dimensions, and
  `WhiteLevel`, including clipping and recoverable-latitude checks
- inspect representative main-image JXL tiles across files and record the
  original-profile/XYB path; apply the same post-inversion stress tests to the
  actual ADC output
- compare ADC JXL DNG directly with standalone JXL made from the same 16-bit
  reference state, both at matched quality settings and near-matched file size
- pass metadata, ICC/color interpretation, and application-compatibility checks,
  including at least one independent decode/render path
- pass blinded visual review on real negatives after realistic inversion and
  grading

Until this gate passes, conclusions must keep standalone verified JXL and ADC
JXL DNG as separate archive candidates and must not describe lossy ADC JXL DNG
as safe as the sole retained master.

## Ready Without New Images

- Run `python scripts\check_publication_ready.py` before sharing.
- Re-run a clean-clone reproduction test after substantial workflow changes.
- Run `python scripts\run_storage_budget_index.py` after ADC candidates are
  generated to check whether PixelShift 16 JXL candidates are actually near the
  single-shot raw storage budget.
- Keep the archived smoke-test page under `docs/archive/`; v2 remains the main
  public result.
- Keep the current selected v2 public figures unless they are replaced by
  stronger anonymized real-negative examples.
- For the private Kodak Gold 200-5 batch, review the generated `d003`/`d005`
  panels and decide which frames, if any, can be replaced by anonymous crops.
- Review the new private Kodak Gold patch-color summaries and use them to pick
  a few representative worst-case crops for future anonymized figures.
- Use `scripts/run_local_scan_study.py --dry-run` after adding each new ignored
  `input/` scan folder, then run it without `--dry-run` once ADC candidates are
  complete.

## When New Images Are Added

- Put new files in ignored local input folders first, not directly in Git.
- Add source sidecars before running tests.
- Mark each image set as safe to publish, crop-only, or private.
- Prioritize one full storage-budget comparison set:
  - 61 MP single-shot raw
  - PixelShift 4
  - PixelShift 16
  - PixelShift2DNG outputs for the practical workflow being tested
- Add anonymous real color-negative frames that stress:
  - dense or underexposed negatives
  - thin or overexposed negatives
  - smooth color transitions or skin-like tones
  - fine grain, dye clouds, or fine texture
  - dust, scratches, hard edges, or high-contrast detail

## Test Order For New Material

1. Intake audit: privacy, source sidecars, SHA-256, dimensions, bit depth, and
   color profile.
2. Baseline render: create the trusted 16-bit reference state.
3. Lossless JXL round trip: require exact pixel match for the chosen state.
4. Conservative lossy matrix: test `d=0.03`, `d=0.05`, and `d=0.10`.
5. Patch-color check: compare registered patches by averaging in linear RGB
   before Lab/`DeltaE00`, and record mean-color bias separately from pixel
   RMSE/noise.
6. Latitude stress: compare after negative-like transforms, curves, channel
   balancing, shadow lifting, and highlight compression.
7. Metadata/ICC diff: check what survives, what is lost, and what needs sidecars.
8. ADC JXL DNG sole-master gate: complete every check in the blocker above;
   opening successfully or preserving selected tags is not sufficient.
9. Standalone-versus-DNG JXL decision: compare both candidates from the same
   reference state and record which, if either, qualifies for sole-master use.
10. Sampling comparison: compare 61 MP raw with 240 MP PixelShift 16 JXL at a
   similar storage budget. If current conservative ADC DNG/JXL candidates do
   not reach the raw budget, report the nearest bracket instead of implying a
   same-size result.
11. Capture-quality measurement: add OpenDICE, AutoSFR, or equivalent target
   measurements if a suitable target capture exists.
12. Update `RESULTS.md`, `CONCLUSIONS.md`, figures, and publication summary.

## Completed

- 2026-08-15: reviewed and finalized `RELATED_WORK.md` and `RESEARCH_PLAN.md`,
  including source-status caveats, a concrete storage-budget definition, and
  separate codec, edit-robustness, sampling, and operational gates.
- 2026-08-18: processed the private Kodak Gold 200-5 batch through Adobe DNG
  Converter lossless, `d=0.03`, `d=0.05`, and `d=0.10` DNG/JXL variants; ran the
  low-level DNG/JXL verification; generated private `d003`/`d005` panels; and
  removed verified duplicate PixelShift2DNG candidates after decoded main-image
  comparison.
- 2026-08-19: added patch-based CIEDE2000/mean-color-bias diagnostics to the
  DNG/JXL verifier, ran the Kodak Gold batch through the new metric, and ran a
  smaller 64 px patch probe on two difficult frame groups.
- 2026-08-19: added a local scan-study runner, reran the existing local film
  material through the same DNG/JXL patch-color verification queue where ADC
  candidates were complete, and added filtered `--source` support to the Adobe
  DNG Converter batch helper.
- 2026-08-19: added `FINDINGS.md` and clarified that FADGI/OpenDICE data belongs
  to the public reproducibility track, while ignored `input/` scans belong to
  the private/local workflow track.
- 2026-08-19: reviewed the selected public latitude v2 figures and documented
  their presentation roles: LOC Golden Gate as the first reader-facing example,
  FADGI/OpenDICE as the reproducibility anchor, and LOC Wildflowers as the
  fine-texture stress case.
- 2026-08-19: added metadata/ICC diff output to the DNG/JXL verifier, including
  per-frame `metadata_diff.csv`/`.json` rows and a preservation-focused summary
  in generated local `SUMMARY.md` files.
- 2026-08-19: regenerated ADC DNG/JXL candidates for the active PixelShift 16
  local scan sets, reran the local study with metadata diff output, and updated
  the tracked findings to reflect the new preservation-review metadata pattern.
- 2026-08-20: merged the local study pipeline into `main`, pushed it, and ran a
  clean-clone readiness check with Git LFS test data.
- 2026-08-20: added a storage-budget index helper and ran it on the current
  private Kodak Gold 200-5 and Kodak Safety Film 5035 scan sets; current ADC
  DNG/JXL candidates remain larger than the paired single-shot ARW baseline even
  at `d=0.10`, so the true same-budget sampling comparison still needs a
  bracketed or different-candidate follow-up.
- 2026-08-20: ran a representative ADC DNG/JXL header inspection on one Kodak
  Gold and one Kodak5035 file; lossless main-image segments used the
  original-profile/non-XYB path, while `d=0.05` main-image segments used lossy
  XYB.
- 2026-08-20: added target-based capture measurement guidance and a concise
  public sharing plan.

## Human Decisions Still Needed

- Which new negatives are safe enough to publish or crop.
- Whether source raw/DNG files may be committed through Git LFS or only measured
  locally.
- Whether a target capture can be added for OpenDICE/AutoSFR-style measurement.
- Where to share first: GitHub only, scanning forum, JPEG XL community,
  photography forum, or a short blog-style writeup.

## Research Questions Still Open

- Does `d=0.05` remain visually acceptable after realistic film inversion and
  grading on real negatives?
- Do low patch-color differences remain low when the comparison is made from a
  fully color-managed renderer/export, not only the low-level DNG raster stress
  pipeline?
- Is `d=0.03` the better practical archival candidate even when its storage
  savings are less dramatic than `d=0.05`?
- Does PixelShift 16 preserve visibly more useful film structure than 61 MP raw
  at the same storage budget?
- Are JPEG XL errors more objectionable in particular film stocks, exposure
  ranges, or color channels?
- Which metadata must be preserved manually if DNG is not the long-term master?
- Do common editing tools handle JXL color profiles consistently enough for this
  workflow?
