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
- Conservative lossy JPEG XL, especially around distance `0.05`, remains a
  plausible secondary/compact master candidate.

## Working Hypothesis

For camera-scanned film, a better-sampled PixelShift image stored as conservative
JPEG XL may preserve more relevant film information than a lower-resolution raw
capture at similar storage cost.

This is not yet proven.

## Next Research Steps

- Add public or anonymized real negative scans.
- Add FADGI/OpenDICE capture-quality tests.
- Add an automated latitude stress transform independent of FilmLab.
- Repeat results across more image types.
- Publish crops and diff panels.
- Invite critique from scanning, archival, and JPEG XL communities.

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
