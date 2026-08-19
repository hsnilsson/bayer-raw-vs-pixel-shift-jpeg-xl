# Research Log

This is a cleaned public-facing log. It preserves the reasoning without exposing
private source images.

## Starting Question

Can JPEG XL make high-resolution PixelShift camera scanning practical as an
archive workflow?

The deeper question became:

> With a fixed storage budget, is it better to preserve fewer pixels as raw data,
> or more film detail as carefully compressed high-resolution RGB?

## Key Findings So Far

- The current short-form interpretation is maintained in
  [CONCLUSIONS.md](../CONCLUSIONS.md).
- PixelShift2DNG files tested so far contain demosaiced/merged linear RGB data,
  not the original camera ARW sensor sequence.
- Lossless JPEG XL can preserve the extracted 16-bit image state exactly.
- Lossless JPEG XL did not save enough space to solve the storage problem by
  itself.
- Lossy JPEG XL can save substantial space, but errors are amplified by
  negative-inversion-like edits.
- FilmLab direct JXL import showed color-management problems in one test, so
  controlled tests should decode JXL externally with `djxl`.
- Conservative lossy JPEG XL remains plausible as a secondary/compact master
  candidate; current local results frame `d=0.03` as cleaner and `d=0.05` as the
  stronger storage compromise.

## Working Hypothesis

For camera-scanned film, a better-sampled PixelShift image stored as conservative
JPEG XL may preserve more relevant film information than a lower-resolution raw
capture at similar storage cost.

This is not yet proven.

## Next Research Steps

- Add public or anonymized real negative scans.
- Add FADGI/OpenDICE capture-quality tests.
- Extend the automated FilmLab-independent latitude stress test to those scans.
- Add metadata/ICC comparison output.
- Run the paired 61 MP raw versus 240 MP PixelShift 16 storage-budget test.
- Repeat results and publish selected crops and diff panels across image types.
- Invite critique from scanning, archival, and JPEG XL communities.

## Related Work And Research Plan Review

On 2026-08-15, the related-work and research-plan drafts were reviewed against
the cited primary standards, vendor documentation, papers, and the repository's
current evidence.

The review made four boundaries explicit:

- DNG 1.7 support for JPEG XL is format support, not an archival endorsement.
- Recent RAWIC, Raw-JPEG Adapter, and whole-slide examples are preprints and are
  treated as adjacent evidence, not preservation standards.
- The primary storage budget covers the retained master plus required sidecars;
  source capture sequences are reported separately.
- Same-state codec metrics and cross-resolution sampling evidence are different
  claims and use different evaluation methods.

## Public Data And Archived Smoke Test

FADGI/OpenDICE targets and three Library of Congress Highsmith master TIFF files
were downloaded with `scripts/download_testdata.py`. Large public test images
are marked for Git LFS.

The first public latitude smoke test used 2048 px crops from one FADGI target
and one LOC photograph. It confirmed that the automated harness worked, but it
was superseded by the v2 density-based test below. The smoke-test page is kept
only as archived project history in
[docs/archive/public-smoke-test.md](archive/public-smoke-test.md).

## Public Latitude Stress v2

The automated public stress test was expanded to six public images and new
density-based negative-print transforms:

- `negative_density_print`
- `negative_density_hard_print`
- `negative_density_shadow_print`

These transforms estimate a simple per-channel base/black point, convert the
crop into an approximate density space, and apply print-like contrast. They are
not a full film renderer, but they stress the same basic concern as the private
FilmLab test: small JPEG XL errors can become more visible after inversion and
grading.

The v2 run confirmed the practical ordering:

- `d=0.03` is the cleanest tested lossy setting.
- `d=0.05` remains the most interesting conservative storage compromise.
- `d=0.10` is consistently worse and should not be treated as archival without
  much stronger evidence.

Selected v2 figures are published in
[docs/public-latitude-v2.md](public-latitude-v2.md).

## Private Kodak Gold 200-5 Batch

On 2026-08-18, a private Kodak Gold 200-5 color-negative batch shot in 1997 was
processed through the ADC DNG/JXL path:

```text
PixelShift2DNG DNG -> Adobe DNG Converter -> DNG 1.7 JPEG XL
```

Nine PixelShift2DNG masters were converted to lossless, `d=0.03`, `d=0.05`, and
`d=0.10` DNG/JXL candidates. Lossless ADC JXL DNG remained exact across 45
low-level crop windows and the scripted transform set. Total batch size changed
from 3.65 GiB for the PixelShift2DNG sources to 3.35 GiB lossless, 2.42 GiB at
`d=0.03`, 1.98 GiB at `d=0.05`, and 1.35 GiB at `d=0.10`.

The lossy results followed the expected ordering. In identity comparison, mean
MAE was 8.59 for `d=0.03`, 14.70 for `d=0.05`, and 28.24 for `d=0.10`.
Hard negative-print transforms amplified the errors substantially, reaching
mean MAE 133.60, 230.43, and 468.69 respectively.

Private visual panels were generated for selected high-error crops at `d=0.03`
and `d=0.05`. They supported the same interpretation: visual differences can be
subtle in direct comparison, while amplified diff views and aggressive negative
transforms expose structured residual errors in grain/density regions.

On 2026-08-19, the DNG/JXL verifier was extended with patch-based color
diagnostics. Each patch is averaged in a declared linear RGB comparison space
before conversion to Lab and CIEDE2000 (`DeltaE00`). This separates local
mean-color bias from pixel-level noise/texture changes.

The full Kodak Gold batch was rerun with 256 px patches. Lossless remained zero
for patch `DeltaE00` and pixel error. For the hard negative-print transform,
median/max patch `DeltaE00` were 0.019/0.067 at `d=0.03`, 0.025/0.087 at
`d=0.05`, and 0.053/0.199 at `d=0.10`. A smaller 64 px patch probe on two
difficult frame groups raised the hard-print median/max values to 0.032/0.115,
0.044/0.135, and 0.090/0.333 respectively, but did not change the ordering.

Interpretation: the latest private raster/stress test suggests `d=0.03` and
`d=0.05` introduce little broad local mean-color bias in this pipeline, even
though pixel/RMSE error after negative-like transforms is much larger. This
strengthens the color-stability case for conservative JXL, but it does not make
lossy JXL safe as the sole master.

This strengthens the internal test case but does not change the publication
boundary: anonymous or public real negative material is still needed before this
can become a shareable community result.
