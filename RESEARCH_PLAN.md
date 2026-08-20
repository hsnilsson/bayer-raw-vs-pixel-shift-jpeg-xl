# Research Plan

This plan turns the related-work review into a stronger test design. The aim is
not to make the project larger for its own sake. The aim is to make the evidence
cleaner, easier to reproduce, and harder to over-interpret.

The core question remains:

```text
At the same storage budget, can a better-sampled PixelShift camera scan stored
as conservative JPEG XL preserve more useful film information than a lower
resolution raw capture?
```

Review status: reviewed on 2026-08-15 against the sources summarized in
[RELATED_WORK.md](RELATED_WORK.md) and against the repository's current public
and private exploratory results. The plan deliberately separates verified
measurements, proposed tests, and decisions that still require evidence.

## Scope And Operational Definitions

### Storage Budget

The primary budget unit is the retained master for one film frame:

```text
single-shot raw/DNG baseline
versus
PixelShift 16 JPEG XL DNG candidate plus required preservation sidecars
```

Source ARW sequence sizes, previews, and temporary working files must be reported
separately. If the proposed archive policy retains the 4- or 16-file source
sequence as well as the merged candidate, the project must report that second
policy explicitly; it cannot use the smaller derived-master total.

A candidate is "size matched" only when its complete retained size is within
5% of the baseline. If encoder settings cannot meet that tolerance, report the
nearest candidate below and above the baseline instead of implying an exact
match.

### Comparison Tracks

The project has four related but distinct outcomes:

1. Codec fidelity: compare identical dimensions and image states before and
   after JPEG XL encoding.
2. Edit robustness: apply identical deterministic transforms to reference and
   candidate states, then compare their outputs.
3. Sampling value: compare paired captures of the same negative using target
   measurements and controlled visual review at a declared common output scale.
4. Operational preservation: test metadata, ICC/color interpretation, decoder
   independence, and application support.

Pixel metrics such as MAE and PSNR are valid for the first two tracks. They must
not be presented as direct evidence that a 240 MP image resolves more film detail
than a 61 MP image unless both are registered to a justified common reference
and scale.

## Source-Driven Improvements

### 1. Treat Preservation Guidance As The Baseline

Sources: Library of Congress Recommended Formats Statement, Library of Congress
DNG format description, and FADGI Technical Guidelines.

Plan impact:

- Keep the practical recommendation conservative until the evidence is much
  stronger.
- Measure and document resolution, bit depth, color profile, metadata, and
  compression choices for every published test.
- Do not frame lossy JPEG XL as a general replacement for DNG, TIFF, or raw
  masters.
- Frame the project as a storage-constrained tradeoff: when keeping the larger,
  better-sampled scan is otherwise impractical, can conservative JPEG XL make it
  viable?

This keeps the work aligned with preservation practice instead of sounding like
an argument against it.

### 2. Separate Codec Claims From Container Claims

Sources: JPEG XL official material, libjxl, Adobe DNG documentation, and DNG
1.7.1.0.

Plan impact:

- Test JPEG XL lossless as an exact pixel-state preservation path.
- Test JPEG XL lossy as an irreversible but possibly useful storage compromise.
- Test DNG metadata and color-management preservation separately from pixel
  preservation.
- Treat DNG-internal JPEG XL as its own track, not as equivalent to external
  `.jxl` files until verified in the actual tools.
- Include Adobe DNG Converter as a practical DNG 1.7 JPEG XL rewrite path for
  PixelShift2DNG output.

The important distinction is:

```text
lossless pixels, lossy pixels, metadata, color profiles, and software support
are different claims.
```

Each claim needs its own evidence.

### 3. Add Objective Capture-Quality Testing

Sources: FADGI Technical Guidelines, OpenDICE, and AutoSFR.

Plan impact:

- Add target-based measurements when possible.
- Use OpenDICE for conformance-style target checks where the available target
  and reference data support it.
- Use AutoSFR or an equivalent spatial-frequency method to measure actual
  resolved detail, not only pixel count.
- Record target version, reference data, capture geometry, magnification, and
  software configuration; a tool name alone is not a measurement method.
- Keep visual crop review, but do not let it be the only evidence for the
  sampling claim.

The project currently has a codec-stress pipeline. It still needs a stronger
capture-quality pipeline.

### 4. Make The Real-Negative Corpus Purposeful

Sources: preservation guidance, FADGI target practice, film-scanning
practitioner concerns, and the existing private tests.

When new anonymous images are added, the corpus should cover failure modes, not
just good-looking frames.

Detailed corpus requirements are in
[TEST_MATERIAL_STRATEGY.md](TEST_MATERIAL_STRATEGY.md).

Minimum useful set:

- one normal color negative
- one dense or underexposed negative
- one thin or overexposed negative
- one frame with smooth color transitions or skin-like tones
- one frame with fine grain, dye clouds, or fine texture
- one frame with hard edges, dust, scratches, or high-contrast detail

For the storage-budget comparison, at least one frame should have all of these:

- 61 MP single-shot raw capture
- PixelShift 4 result
- PixelShift 16 result
- PixelShift2DNG output files, if that is the practical workflow being tested

This is the single most important upcoming dataset.

### 5. Test After Film-Like Stress, Not Only Before It

Sources: raw-compression research, digital pathology compression analogies, and
the project's FilmLab observations.

Plan impact:

- Continue to measure identity/decode error.
- Also measure after negative-like transforms, contrast expansion, channel
  balancing, shadow lifting, and highlight compression.
- Keep FilmLab as a practical reality check, but prefer an automated
  FilmLab-independent transform for reproducible public results.
- Measure high-percentile error and per-channel bias, not only average error.

Small JXL errors that are invisible before inversion may matter after inversion.
The test design should make that risk visible.

### 6. Test The Sampling Hypothesis Directly

Sources: multi-frame super-resolution research and PixelShift practice.

Plan impact:

- Compare a lower-resolution raw capture with a higher-resolution PixelShift
  capture of the same negative.
- Hold camera, lens, aperture, focus, magnification, film position, illumination,
  exposure normalization, and rendering choices constant or document every
  unavoidable difference.
- Normalize the comparison by storage budget, not just by capture mode.
- Create JPEG XL candidates from the PixelShift 16 file at distances that bracket
  the target size of the 61 MP raw/DNG baseline.
- Keep four controls: the 61 MP baseline, the uncompressed or lossless PixelShift
  16 upper bound, a PixelShift 16 lossless-JXL round trip, and the size-matched
  lossy PixelShift 16 candidate. Add a PixelShift 16 result downsampled to the
  declared common output scale when it helps separate sampling from display
  magnification.
- Review crops where additional sampling should matter: dye clouds, fine grain,
  lettering, scratches, edge detail, and subtle local density changes.
- Also check for PixelShift failure: movement, registration artifacts, lens
  limits, diffraction, unstable film holder, or lighting instability.

This is the heart of the project. Without this track, the work is mostly a JPEG
XL stress test. With it, the work becomes an actual answer to the storage
tradeoff.

### 7. Add A Metadata And ICC Gate

Sources: Library of Congress metadata emphasis, DNG documentation, JPEG XL file
format support, and the project's earlier metadata-diff discussion.

Plan impact:

- Run an ExifTool-based metadata diff for every master/candidate path.
- Record embedded ICC profiles or explicitly stated color spaces.
- Decide which metadata must be embedded, which may live in sidecars, and which
  is irrelevant for the public test.
- Treat missing camera/lens/capture/process metadata as an archival weakness even
  when pixels look good.

Suggested required metadata groups:

- source file identity and SHA-256
- capture date or anonymized capture batch
- camera and lens model, if not privacy-sensitive
- pixel dimensions and bit depth
- color profile or working color space
- PixelShift mode and PixelShift2DNG version/settings
- JPEG XL encoder, decoder, distance, effort, and decode command
- processing pipeline and tool versions

### 8. Use Decision Gates Instead Of A Single Score

No single metric can answer archival value. The project should therefore use
gates.

Lossless gate:

- decoded pixels must match the chosen reference state exactly
- max error `0`
- MAE `0`
- metadata/color profile expectations must be documented separately
- the external `.jxl` path and DNG-internal JXL path must be reported separately
- at least one independent decoder or render path must confirm the final
  preservation claim

Conservative lossy candidate gate:

- crop locations and stress categories are selected from the reference before
  inspecting codec labels
- no visible artifacts in selected post-inversion crops during close review
- no objectionable changes in dense shadows, highlights, smooth color, or skin-
  like tones
- no suspicious per-channel bias
- numeric acceptance thresholds are frozen after the pilot and before the main
  corpus is evaluated; raw per-image results remain published even when a gate
  fails
- file size meets the storage-budget target
- results are reproduced across more than one negative
- blinded visual review records viewer, zoom, display conditions, and whether
  the reference can be distinguished from the candidate

Sampling gate:

- PixelShift 16 must show real extra film detail over 61 MP single-shot raw
- the advantage must survive the chosen JPEG XL setting
- PixelShift artifacts must not outweigh the extra detail
- the retained-master size must meet the predeclared 5% tolerance or be reported
  as a bracketed comparison
- sampling evidence must use target/SFR results or controlled visual review at a
  declared common output scale, not cross-resolution MAE or PSNR alone

Operational gate:

- metadata and ICC/color interpretation meet the declared preservation profile
- the candidate opens and renders consistently in the named archival and editing
  tools
- failures are reported per application and version, rather than generalized to
  the JPEG XL or DNG formats

Additional sole-master gate for lossy Adobe DNG Converter JXL DNG:

- the original PixelShift2DNG and ADC output are rendered through the same
  trusted pipeline and compared over the same registered crop
- the observed changes in stored dimensions, crop, and `WhiteLevel` are
  explained and tested for clipping, rescaling, and loss of editable latitude
- representative main-image tiles are inspected across files; the inferred
  original-profile/XYB path is recorded and the actual ADC result is subjected
  to the same post-inversion stress tests as standalone JXL
- ADC JXL DNG is compared directly with standalone JXL from the same 16-bit
  reference state at matched quality settings and near-matched retained size
- metadata, ICC/color interpretation, named-application behavior, and at least
  one independent decode/render path pass the operational gate
- blinded review of real negatives finds no objectionable difference after the
  declared inversion and grading workflow

Until every item in this additional gate passes, lossy ADC JXL DNG remains an
experimental candidate and must not be recommended as the sole retained master.
Successful conversion, plausible tags, or successful opening in one application
are not sufficient.

Publication gate:

- public or anonymized data only
- source sidecars and SHA-256 hashes present
- tool versions recorded
- selected figures explain the result without relying on private files
- limitations remain visible in README, conclusions, and publication summary

## Near-Term Execution Order

1. [x] Finish and review the related-work and research-plan documentation
   (completed 2026-08-15).
2. [ ] Add anonymous real-negative test material under ignored local input
   folders.
3. [ ] Create source sidecars for each new image set.
4. [ ] Run the existing lossless and lossy JPEG XL tests on the new material.
5. [ ] Run latitude-stress tests on the new material.
6. [ ] Add metadata/ICC diff output.
7. [ ] Test Adobe DNG Converter DNG 1.7 JPEG XL output through the same render and
   metadata gates.
8. [ ] Run the storage-budget comparison: 61 MP raw versus 240 MP PixelShift 16
   JXL.
9. [ ] Add target-based capture-quality measurements if a suitable target
   capture is available.
10. [ ] Update `RESULTS.md`, `CONCLUSIONS.md`, and public figures.
11. [ ] Ask for outside critique only after the real-negative and storage-budget
    tracks are represented.

## What To Add Next

When new images are ready, add them locally but do not commit them immediately.
Use ignored folders first, for example:

```text
input/anonymous_negatives/
input/sampling_budget_comparison/
```

For each image set, add a small sidecar note with:

- what the image is intended to stress
- capture mode: single-shot, PixelShift 4, or PixelShift 16
- source format: ARW, DNG, TIFF, or another format
- PixelShift2DNG version/settings if used
- camera, lens, aperture, ISO, light source, and film holder notes
- privacy status: safe to publish, crop-only, or private
- whether the source may be committed through Git LFS
- complete retained-master size and the separately reported source-sequence size

The first new set should prioritize the direct storage-budget comparison. That
is the test most likely to make the project genuinely useful to other camera
scanners.

## Current Storage-Budget Reality Check

The local helper `scripts/run_storage_budget_index.py` now checks whether the
ignored local scan folders contain paired single-shot raw and PixelShift 16 ADC
JXL DNG candidates that are size-comparable.

On the current private Kodak Gold 200-5 and Kodak Safety Film 5035 scan sets,
the ADC DNG/JXL candidates at `lossless`, `d=0.03`, `d=0.05`, and `d=0.10`
remain larger than the paired single-shot ARW files. That does not invalidate
the sampling hypothesis, but it means the current ADC JXL DNG settings do not
yet produce a true same-storage comparison against 61 MP ARW on these files.

The next storage-budget step is therefore either:

- bracket the 61 MP raw budget with a more aggressive candidate and report that
  it is outside the current conservative range, or
- compare against a different retained-master baseline, such as PixelShift 4
  DNG or a rendered 16-bit master, and label that policy explicitly.

Any such comparison must still pass the sampling, color, inversion-stress, and
operational gates before it can support an archive recommendation.
