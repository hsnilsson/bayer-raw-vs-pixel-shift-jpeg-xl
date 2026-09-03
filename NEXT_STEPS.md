# Next Steps

This is the maintained execution queue. Completed work is recorded in
[`docs/research-log.md`](docs/research-log.md); methodological boundaries are in
[`LIMITATIONS.md`](LIMITATIONS.md).

## Current Result

The current local matrix places the median storage crossing between `d022`
(106.4% of paired RAW61 size) and `d025` (86.3%). Levels `d025` through `d030`
are the active under-budget candidates. `d100`, `d150`, and `d200` are visual
stress references only and must not receive archive-candidate verdicts.

This is evidence from the current material, not a universal recommendation to
discard RAW/DNG masters.

## Before Calling The Current Study Complete

1. Record a structured visual review of representative `d022` through `d030`
   crops, including normal, shadow-recovery, highlight-separation, and hard
   negative-density views. Keep codec damage separate from RAW61-versus-PS16
   sampling differences.
2. Freeze one report build and run `python scripts/check_publication_ready.py`.
3. Reproduce that frozen build from a clean clone, including Git LFS public test
   data and the documented external tools.
4. Publish the report and request critique of the metric definitions,
   registration, color handling, and fixed-storage decision rule.

## When New Film Material Is Available

Add complete triplets where practical:

- 61 MP single-shot ARW
- PixelShift 4 source sequence and merged DNG
- PixelShift 16 source sequence and merged DNG

Prioritize material that broadens the evidence rather than repeating an easy
frame: dense and thin negatives, saturated colors, skin-like tones, smooth
gradients, fine dye-cloud/grain structure, hard edges, scratches, and difficult
mixed-density scenes.

For each accepted set:

1. Place sources under ignored `input/` storage and create/update the manifest
   and publication annotation.
2. Render RAW61 and PS16 through the declared RawTherapee profile.
3. Register RAW61 locally to PS16 and review the recorded shift/confidence.
4. Generate standalone PS16 JXL levels spanning `d003` through `d030`; retain
   `d100`/`d200` only as obvious-damage references in the viewer.
5. Run size, patch-color, stress-color, and high-pass structure measurements.
6. Generate only missing review assets through the incremental cache.
7. Review the new crops, regenerate the report, and rerun publication checks.

## Deliberately Out Of Scope

- **OpenDICE application integration:** public FADGI/OpenDICE TIFFs remain
  reproducible codec inputs, but running the OpenDICE application on its own
  sample does not test this camera-scanning workflow.
- **Sony Imaging Edge merge comparison:** the study measures codec loss after
  one declared PixelShift2DNG merge path and does not compare merge software.
- **ADC DNG/JXL as the primary candidate:** the measured path changes geometry,
  sample interpretation, and metadata dependencies and is incompatible with the
  reference renderer. The core verdict uses standalone JXL from a fixed PS16
  render.
- **Negative-aware preconditioning before JXL:** no measured benefit justifies a
  custom representation and inverse transform for an archive master.

## Optional Evidence That Would Strengthen, Not Block, The Result

- Independent reproduction on another camera-scanning setup.
- A physical resolution target captured as both RAW61 and PS16 under the same
  optical conditions.
- Blinded ratings from additional reviewers.
- More film stocks and exposure conditions using the same frozen pipeline.
