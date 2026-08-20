# Archival Value Metrics

This document defines how the project should evaluate the question:

```text
At what JPEG XL compression level does a 240 MP PixelShift 16 master stop
carrying more archival value than a 61 MP single-shot raw file?
```

It is a metric specification, not a result. Its job is to prevent the project
from substituting convenient image-difference numbers for the actual archival
question.

## Source Basis

The metric design follows these external ideas:

- The Library of Congress Recommended Formats Statement emphasizes faithful
  representation, high resolution, high bit depth, embedded or specified color
  space, low/lossless compression, metadata, and no access-control technology
  for digital photographs.
- FADGI still-image guidance treats digitization as a measured process and
  expects technical guidelines, conformance targets, software, monitoring, and
  quality management to work together.
- FADGI OpenDICE and AutoSFR separate capture conformance and actual resolution
  measurement from ordinary visual inspection.
- ISO 12233 frames resolution as spatial frequency response, not simply pixel
  count.
- CIEDE2000 is a standardized color-difference formula intended to better model
  perceived small color differences than raw XYZ or Lab distances.
- JPEG XL can be lossless or lossy, and lossy JPEG XL may use XYB rather than
  storing RGB values directly in the original profile. This makes post-inversion
  testing relevant for color-negative workflows.
- DNG, Exif, XMP, MIX/NISO technical metadata, PREMIS-style preservation
  metadata, and format validation all matter because image quality alone is not
  preservation.

## Working Definition Of Archival Value

For this project, archival value means:

```text
the retained file or file set preserves the most useful recoverable information
about the film frame for future rendering, interpretation, and reuse, under a
declared storage budget and a declared preservation policy.
```

This has four dimensions:

1. **Sampling value**: real film structure was captured and remains usable.
2. **Color and tone value**: color, density relationships, and editable latitude
   survive ordinary and stressful negative-processing operations.
3. **Codec fidelity**: JPEG XL loss does not erase useful information or create
   misleading artifacts beyond the loss already present in the 61 MP raw path.
4. **Operational preservation**: files remain identifiable, decodable,
   color-manageable, documented, and reproducible with preserved metadata or
   sidecars.

No single metric can represent all four dimensions.

## Reference States

The break-even test needs three image states:

```text
R16 = best available PixelShift 16 reference state
R61 = 61 MP single-shot raw rendered through the same declared pipeline
J16(d) = PixelShift 16 JPEG XL candidate at distance d
```

`R16` is not the literal truth of the film. It is the best available practical
reference produced by the workflow under test. It must be declared and kept
fixed before looking at candidate labels.

All comparisons must use registered scene coordinates. If dimensions differ,
the project must declare whether the comparison is:

- **native-detail comparison**: `R61` is registered and upsampled to the `R16`
  scene grid to ask what the 61 MP capture failed to sample
- **common-output comparison**: both states are rendered to a shared output
  scale to ask what a viewer or editor can actually use at that scale
- **target/SFR comparison**: a physical target is measured according to a
  declared target method

The first two are complementary. Neither alone is enough.

## Break-Even Rule

For each JPEG XL distance or encoder setting, compare two losses:

```text
RAW loss:  R61 -> R16
JXL loss:  J16(d) -> R16
```

The rough break-even point is where:

```text
JXL loss is no longer clearly lower than RAW loss
```

This must be evaluated per evidence group:

- color and tone
- post-inversion latitude
- structure/detail
- visible artifacts
- metadata and operational preservation
- retained-master size

The result should be reported as zones, not as a false-precision single number:

```text
PS16 JXL clearly wins
uncertain / image-dependent
RAW61 clearly wins
```

## Metric Tiers

### Gate Metrics

These are pass/fail requirements. A candidate that fails a gate cannot be
recommended as a sole archive master even if it scores well elsewhere.

- retained-master size and required sidecars are reported
- source hashes, candidate hashes, tool versions, and commands are recorded
- the reference and candidate are rendered through the same declared pipeline
- images are registered before comparison
- color profile or color space is embedded, preserved, or documented
- DNG geometry, crop, `WhiteLevel`, opcodes, and compression tags are reviewed
- at least one independent decoder or render path is tested before a
  sole-master claim
- no unexplained clipping, channel truncation, or metadata loss is accepted as
  harmless

### Primary Metrics

These metrics can support the archival-value conclusion.

#### Color And Tone

- patch mean `DeltaE00`, computed after averaging each patch in linear RGB or
  XYZ and then converting the patch mean to Lab
- median, mean, p95, p99, and max `DeltaE00`
- per-channel bias in linear comparison space
- results grouped by luminance, chroma, and negative density
- clipping counts and near-clipping counts before and after stress transforms
- repeated measurements after negative-like transforms, density mapping, channel
  balancing, shadow lift, highlight compression, and curve expansion

Purpose:

```text
detect systematic color/tone movement and latent post-inversion damage
```

#### Sampling And Structure

- target-based SFR/MTF or AutoSFR/OpenDICE-style measurements when suitable
  target captures exist
- registered crop review at native-detail scale for dye clouds, grain, text,
  scratches, dust, edges, and high-contrast detail
- registered crop review at common output scale
- blind or label-hidden visual ranking when possible
- frequency-band or edge-detail preservation measurements, reported per crop and
  never as the sole conclusion

Purpose:

```text
decide whether the 240 MP PixelShift state preserves useful film structure that
the 61 MP raw state does not
```

### Secondary Metrics

These metrics are useful, but they cannot carry the archival conclusion alone.

- RMSE, MAE, PSNR
- p95/p99/p99.9 pixel error
- SSIM or MS-SSIM
- high-pass residual energy
- local noise/variance changes
- error relative to reference patch variance

Purpose:

```text
diagnose where and how files differ
```

These metrics are especially useful when comparing `J16(d)` to `R16`, because
the dimensions and image state can be identical. They are less decisive for
`R61` versus `R16`, where some difference is the intended sampling difference.

### Operational Metrics

These are archival-risk measurements rather than visual-quality measurements.

- file format identification and validation where tools support the format
- ExifTool metadata diff
- ICC/profile hash or profile-name comparison
- DNG tag review, including shape, active crop, `WhiteLevel`, `BlackLevel`,
  `ColorMatrix`, `AsShotNeutral`, `OpcodeList`, `OpcodeList2`, and JXL tags
- sidecar completeness for any metadata not safely embedded
- successful decode/render in named software versions
- JXL codestream path: lossless/original-profile versus lossy/XYB where tools
  expose it

Purpose:

```text
measure whether the file can be trusted, understood, and reconstructed later
```

## Metrics That Must Not Be Used As The Verdict

The project must not decide archival value from:

- PSNR alone
- MAE alone
- SSIM alone
- one full-image aggregate score
- unregistered crops
- raw sensor code comparisons between ARW and rendered PixelShift DNG/JXL
- comparison through different renderers or different tone/color settings
- JXL-vs-lossless-JXL only, without comparing 61 MP raw against the same
  PixelShift reference
- file size alone
- visual inspection only, unless clearly labeled as anecdotal

## Proposed Break-Even Table

Each frame or crop group should eventually produce rows like this:

```text
distance
retained_size_mib
size_vs_raw61_pct
color_delta_e00_p95_identity
color_delta_e00_p95_stress
channel_bias_max_stress
clipping_delta_stress
raw61_structure_loss
jxl_structure_loss
artifact_risk
metadata_risk
verdict
```

The verdict should use controlled language:

- `ps16_jxl_wins`
- `ps16_jxl_likely_wins`
- `uncertain`
- `raw61_likely_wins`
- `raw61_wins`
- `blocked_by_operational_risk`

## Acceptance Logic

`PS16 JXL wins` when:

- it is within the declared storage-policy comparison, or is clearly labeled as
  the nearest bracket
- color/tone errors after stress remain lower than or comparable to `R61 -> R16`
- structure/detail evidence shows useful information remains beyond the 61 MP
  raw path
- visible artifacts are absent or less important than the extra sampled detail
- operational gates pass

`RAW61 wins` when:

- JXL compression damage after stress is greater than the useful sampling gain
- fine structure is smeared, hallucinated, or made misleading
- color or density errors become objectionable after realistic inversion
- the JXL candidate requires compression so aggressive that artifacts dominate
- metadata/color/decode behavior fails the sole-master gate

`Uncertain` is the correct result when color and structure disagree, target data
is missing, registration is weak, or visual review is not yet sufficient.

## Immediate Implementation Implications

The next break-even script should not output one score. It should output:

- one size curve
- one color/tone curve
- one post-inversion stress curve
- one structure/detail curve
- one operational-risk table
- one conservative verdict per candidate

The script should also report nearest-above and nearest-below storage brackets
when no JPEG XL setting lands within 5% of the 61 MP raw baseline.

## References

- [Library of Congress Recommended Formats Statement: Still Image Works](https://www.loc.gov/preservation/resources/rfs/stillimg.html)
- [FADGI Technical Guidelines for Digitizing Cultural Heritage Materials](https://www.digitizationguidelines.gov/guidelines/digitize-technical.html)
- [FADGI OpenDICE and AutoSFR](https://www.digitizationguidelines.gov/guidelines/digitize-OpenDice.html)
- [FADGI Technical Guidelines Resources](https://www.digitizationguidelines.gov/guidelines/digitize-technical-resources.html)
- [ISO 12233:2024 summary](https://www.iso.org/standard/88626.html)
- [CIEDE2000, ISO/CIE 11664-6:2022](https://www.cie.co.at/publications/colorimetry-part-6-ciede2000-colour-difference-formula-1)
- [JPEG XL format overview, libjxl](https://github.com/libjxl/libjxl/blob/main/doc/format_overview.md)
- [JPEG XL reference implementation, libjxl](https://github.com/libjxl/libjxl)
- [Adobe Digital Negative resources](https://helpx.adobe.com/camera-raw/digital-negative.html)
- [ANSI/NISO Z39.87 technical metadata for digital still images](https://www.niso.org/publications/ansiniso-z3987-2006-r2017-data-dictionary-technical-metadata-digital-still-images)
- [PREMIS for Digital Preservation](https://www.digitalpreservation.gov/series/challenge/premis.html)
- [JHOVE documentation](https://jhove.openpreservation.org/documentation/)
