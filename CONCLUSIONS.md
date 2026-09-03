# Conclusions

This is the short version of the project so far.

The project asks whether conservative JPEG XL can make very high-resolution
PixelShift camera scanning practical for film archiving. The point is not that
lossy JPEG XL is identical to raw. It is not. The question is whether, at the
same storage budget, a better-sampled image stored with careful JPEG XL settings
can preserve more useful film information than a lower-resolution raw capture.

## Current Answer

The current practical answer is:

- Do not delete original DNG, ARW, or other raw/lossless masters based on this
  evidence alone.
- JPEG XL lossless can preserve a chosen 16-bit rendered/extracted image state
  exactly, but the storage savings were modest in the tested PixelShift2DNG
  files.
- Conservative lossy JPEG XL remains promising as a compact secondary master or
  working archive format.
- JPEG XL distance `0.03` is the cleaner conservative lossy candidate tested so
  far; distance `0.05` is the more interesting storage compromise.
- JPEG XL distance `0.10` looks too aggressive for an archival claim without
  much stronger evidence.
- The newest patch-color tests make `d=0.03` and `d=0.05` look better for local
  mean-color stability than the raw pixel-error numbers alone suggested, but
  they do not remove the sole-master risk.
- The newest standalone rendered-PS16 JXL matrix crosses the paired 61 MP RAW
  storage budget between `d022` and `d025` on the current local material.
  `d025` through `d030` are under budget in the current metrics, but require
  broader material, blinded visual review and independent reproduction before
  becoming a practical recommendation. `d100` and `d200` are visual stress
  references, not archive candidates.
- A new one-frame muimg feasibility probe crossed the paired RAW61 budget
  between `d006` and `d007` while preserving the checked DNG geometry, white
  level, and color metadata. This materially improves the direct-DNG outlook,
  but current application support and the one-frame scope keep it outside the
  decision-grade verdict.

The deeper hypothesis remains alive: a very high-resolution PixelShift scan
stored as conservative JPEG XL may be a better practical representation of a
film frame than a much lower-resolution single-shot raw file stored losslessly,
if both choices consume about the same disk space.

## Why This Is Plausible

Film scanning is not only about preserving numeric precision. It is also about
sampling the physical structure of the film:

- dye clouds
- grain-like texture
- scratches and dust
- edge detail
- subtle local density variation

If a lower-resolution capture barely resolves that structure, it may preserve
many precise numbers without preserving enough of the original object. A
higher-resolution PixelShift image may capture more relevant spatial structure,
even if conservative lossy compression slightly changes some pixel values.

That tradeoff is the heart of this project.

## What The Tests Support

The local exploratory tests support these points:

- PixelShift2DNG output tested here behaves like demosaiced/merged RGB image
  data, not like the original sequence of sensor raw files.
- Lossless JPEG XL round-tripped extracted 16-bit linear image data exactly.
- Lossless JPEG XL did not save enough space to solve the storage problem by
  itself.
- Negative inversion and strong tonal edits can amplify small JPEG XL errors.
- A local Kodak Gold 200-5 batch repeated the same basic ordering on real
  color-negative camera scans: lossless ADC JXL DNG was exact in tested crops,
  `d=0.03` was cleaner, and `d=0.05` saved more space while showing larger
  errors after negative-like transforms.
- Patch-based CIEDE2000 tests on that batch found very low local mean-color
  differences for `d=0.03` and `d=0.05`, even after hard negative-print stress.
  This suggests much of the measured lossy penalty is texture/pixel variation
  rather than broad patch-level color bias.
- A second local Kodak Safety Film 5035 set repeated the same ordering:
  lossless exact, `d=0.03` cleaner, `d=0.05` smaller with higher error, and
  `d=0.10` clearly riskier. Its hard-print patch-error tail was higher than the
  Kodak Gold set, so p95/max patch metrics remain important.
- The new metadata/ICC diff pass strengthens the sole-master caution for Adobe
  DNG Converter lossy JXL DNG: lossless had no preservation-review metadata
  changes in the active PixelShift 16 local runs after rational DNG tag
  normalization, while lossy candidates rewrote stored raster shape, active crop
  origin, `WhiteLevel`, and `OpcodeList2`.
- On one Adox resolution-target frame, muimg lossless DNG/JXL was pixel-exact;
  its preview-bearing `d007` output was 94.6% of paired RAW61 size and kept the
  checked image geometry and color metadata. RawTherapee and darktable could not
  open it, and sampled lossy tiles used XYB, so an equivalent negative-aware
  end-to-end render comparison is still unavailable.
- A local FilmLab ProPhoto test found `d=0.05` much less damaging than more
  aggressive distances after inversion, while reducing one selected DNG to about
  half its size.

The public tests support these points:

- The repository now has a reproducible public test pipeline.
- FADGI/OpenDICE target files are part of that public pipeline. They are used
  to make the codec and negative-like stress tests reproducible, not as
  substitutes for real PixelShift film scans.
- Public latitude-stress v2 tests show that `d=0.10` is consistently worse than
  `d=0.05`.
- Density-based negative-print transforms expose larger high-percentile errors
  than identity comparison, which is relevant to color-negative workflows.
- The current public results make `d=0.05` look like a reasonable conservative
  candidate to keep testing, not a proven replacement for raw.

## What The Tests Do Not Prove

The tests do not prove that lossy JPEG XL is archival-safe as the only master.

They do not prove that `d=0.05` will survive every future edit, inversion style,
film stock, exposure error, or color-management workflow.

They do not prove that PixelShift is always superior. PixelShift can fail or
lose its advantage through movement, registration errors, lens limits,
diffraction, lighting issues, or unstable film holders.

They also do not prove that the public test images fully represent real
camera-scanned negatives. The public data is useful and reproducible, while the
owner-approved real-negative corpus remains too limited for a general claim.

## Practical Recommendation Today

For irreplaceable work:

- Keep original raw/DNG files when possible.
- Use JPEG XL lossless when exact preservation of a chosen rendered state is
  needed and modest savings are still useful.
- Treat JPEG XL `d=0.03`/`d=0.05` as high-quality secondary or evaluation
  masters when their larger size is acceptable, not as the fixed-budget answer.
- Treat the current under-budget boundary around `d025` as a research result
  requiring visual review, not yet as a sole-master recommendation.
- Be very cautious with `d=0.10` for archival use.
- Test after the edits that matter: inversion, color balancing, curves, shadow
  lifting, highlight recovery, and wide-gamut export.
- Read patch-color metrics and pixel metrics together: low patch `DeltaE00` is
  reassuring about mean color, but high pixel/RMSE after stress can still matter
  if the preserved subject is grain, dye clouds, scratches, or fine density
  structure.

For a storage-constrained camera-scanning workflow, the interesting candidate is
not "replace everything with lossy JPEG XL." It is:

```text
capture more real film detail with high-resolution PixelShift,
then use conservative JPEG XL only after testing the exact workflow.
```

## What Would Change The Recommendation

The case for JPEG XL would become stronger if:

- anonymous real color-negative PixelShift scans repeat the public v2 pattern
- blind visual comparisons do not reveal meaningful differences at `d=0.05`
- latitude-stress tests remain clean after stronger film-like transforms
- physical target measurements show a clear sampling advantage for the
  higher-resolution PixelShift workflow
- results are reproduced by other people with different scanners, cameras,
  films, and software

The case would become weaker if:

- `d=0.05` produces visible artifacts after realistic inversion and grading
- errors cluster in skin tones, dense shadows, highlights, or smooth color
  transitions
- PixelShift registration or lens limits erase the expected resolution advantage
- metadata or color-management handling proves fragile in common software

## Bottom Line

JPEG XL is not magic raw compression. It throws information away when used
lossily.

But film archiving under a fixed storage budget is not only a per-pixel
precision problem. It is also a sampling problem. If conservative JPEG XL makes
it practical to store much better-sampled scans, it may preserve more of what
matters in the film frame than a smaller raw capture that never sampled that
detail in the first place.

That is still a hypothesis, but it is now specific enough to test.
