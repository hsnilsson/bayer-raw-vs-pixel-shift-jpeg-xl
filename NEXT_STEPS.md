# Next Steps

This file is the short execution queue. The rationale is in
[RESEARCH_PLAN.md](RESEARCH_PLAN.md), input-material requirements are in
[TEST_MATERIAL_STRATEGY.md](TEST_MATERIAL_STRATEGY.md), and the prior-art
framing is in [RELATED_WORK.md](RELATED_WORK.md).

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

## Ready Without New Images

- Run `python scripts\check_publication_ready.py` before sharing.
- Run a clean-clone reproduction test on another machine or in another folder.
- Review selected v2 public figures in `docs/figures/` and remove any that feel
  too noisy, redundant, or visually confusing.
- Keep the archived smoke-test page under `docs/archive/`; v2 remains the main
  public result.

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
5. Latitude stress: compare after negative-like transforms, curves, channel
   balancing, shadow lifting, and highlight compression.
6. Metadata/ICC diff: check what survives, what is lost, and what needs sidecars.
7. ADC JXL DNG check: test DNG 1.7 lossless and `d=0.05` output through a
   controlled render pipeline.
8. Sampling comparison: compare 61 MP raw with 240 MP PixelShift 16 JXL at a
   similar storage budget.
9. Capture-quality measurement: add OpenDICE, AutoSFR, or equivalent target
   measurements if a suitable target capture exists.
10. Update `RESULTS.md`, `CONCLUSIONS.md`, figures, and publication summary.

## Completed

- 2026-08-15: reviewed and finalized `RELATED_WORK.md` and `RESEARCH_PLAN.md`,
  including source-status caveats, a concrete storage-budget definition, and
  separate codec, edit-robustness, sampling, and operational gates.

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
- Does PixelShift 16 preserve visibly more useful film structure than 61 MP raw
  at the same storage budget?
- Are JPEG XL errors more objectionable in particular film stocks, exposure
  ranges, or color channels?
- Which metadata must be preserved manually if DNG is not the long-term master?
- Do common editing tools handle JXL color profiles consistently enough for this
  workflow?
