# Adobe DNG Converter JPEG XL DNG Smoke Test

Date: 2026-08-15

Purpose: test whether Adobe DNG Converter can rewrite existing PixelShift2DNG
files as DNG 1.7 files with internal JPEG XL compression.

This is a smoke test, not a full archival validation. It verifies that the files
are written, that the DNG/JXL tags look right, and that key metadata survives.
This smoke test by itself does not prove pixel identity or post-inversion
safety; those questions are handled by the later verification and stress-test
tracks.

## Tool

Adobe DNG Converter 18.5 for Windows.

Executable:

```powershell
C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe
```

The `-o outputfile.dng inputfile.dng` form returned success but did not write an
output file in this local test. The working form was:

```powershell
& "C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe" `
  -losslessJXL `
  -d outputs\adc_jxl_test\lossless_batch `
  input.dng
```

For the lossy smoke test:

```powershell
& "C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe" `
  -lossy `
  -jxl_effort 7 `
  -jxl_distance 0.05 `
  -d outputs\adc_jxl_test\lossy_d005_batch `
  input.dng
```

## Result

Adobe DNG Converter accepted the PixelShift2DNG files and wrote DNG 1.7 files
with JPEG XL compression.

For lossless output, ExifTool reported:

```text
DNGVersion: 1.7.0.0
DNGBackwardVersion: 1.7.0.0
SubIFD Compression: JPEG XL
SubIFD PhotometricInterpretation: Linear Raw
SubIFD BitsPerSample: 16 16 16
SubIFD SamplesPerPixel: 3
SubIFD JXLDistance: 0
SubIFD JXLEffort: 7
SubIFD JXLDecodeSpeed: 4
```

For lossy `d=0.05`, ExifTool reported:

```text
DNGVersion: 1.7.0.0
DNGBackwardVersion: 1.7.0.0
SubIFD Compression: JPEG XL
SubIFD PhotometricInterpretation: Linear Raw
SubIFD BitsPerSample: 16 16 16
SubIFD SamplesPerPixel: 3
SubIFD JXLDistance: 0.0500000007450581
SubIFD JXLEffort: 7
SubIFD JXLDecodeSpeed: 4
```

## Embedded JPEG XL Color Path

The first two tiles in the main `LinearRaw` IFD from one private lossless output
and its lossy `d=0.05` counterpart were copied byte-for-byte using the TIFF
`TileOffsets` and `TileByteCounts` tags and inspected with `jxlinfo` from libjxl
0.11.2. Preview IFDs were kept separate from this comparison.

| ADC output | `jxlinfo` classification | Signaled encoding | Inferred internal color path |
| --- | --- | --- | --- |
| lossless JXL DNG | `(possibly) lossless` | Rec.2100 primaries, linear transfer | original profile, non-XYB |
| lossy JXL DNG `d=0.05` | `lossy` | Rec.2100 primaries, sRGB transfer | XYB |

This inference follows libjxl's `JxlBasicInfo.uses_original_profile` flag. The
[`jxlinfo` source](https://github.com/libjxl/libjxl/blob/main/tools/jxlinfo.cc)
prints `(possibly) lossless` when that flag is true and `lossy` when it is false;
the libjxl
[format overview](https://github.com/libjxl/libjxl/blob/main/doc/format_overview.md)
identifies `uses_original_profile = false` as the XYB color path.

This matters because the outer DNG still identifies the image as camera-native
`LinearRaw`: the DNG container does not imply that its lossy JXL tiles avoid
perceptual XYB coding. The signaled Rec.2100/sRGB encoding describes the embedded
JXL conversion path; it does not by itself prove that the rendered DNG is
Rec.2100/sRGB or that Adobe's decoding is colorimetrically wrong. It means that
a same-render and post-inversion comparison is required before this
representation can be treated as a preservation candidate.

This was a header check of two tiles in one private file pair, not a corpus or
exhaustive tile result. Repeat it across files and representative tiles before
generalizing the finding, and keep the lossless and lossy paths separate.

## Size

| File | PixelShift2DNG | ADC lossless JXL DNG | Lossless % | ADC JXL DNG d=0.05 | d=0.05 % |
| --- | ---: | ---: | ---: | ---: | ---: |
| `private-scan-1.dng` | 173.54 MiB | 152.25 MiB | 87.7% | 88.41 MiB | 50.9% |
| `private-scan-2.dng` | 184.65 MiB | 157.83 MiB | 85.5% | 92.51 MiB | 50.1% |
| `private-scan-3.dng` | 145.80 MiB | 125.60 MiB | 86.1% | 83.95 MiB | 57.6% |

Interpretation:

- Lossless JPEG XL DNG saved roughly 12-15% on these three files.
- Lossy `d=0.05` JPEG XL DNG saved roughly 42-50%.
- Lossless savings are useful but not enough to solve storage by themselves.
- Lossy DNG/JXL is now a serious candidate for the same storage-budget question,
  but it needs a fresh pixel/render/inversion test because Adobe DNG Converter
  changes more than just the compression tags.

## Metadata Notes

For lossless JXL DNG, key image metadata was preserved:

```text
SubIFD ImageWidth: 9600
SubIFD ImageHeight: 6376
DefaultCropSize: 9552 6360
BlackLevel: 0 0 0
WhiteLevel: 14848 14848 14848
ColorMatrix1: unchanged
ColorMatrix2: unchanged
AsShotNeutral: unchanged
Make/Model/LensModel: preserved
SerialNumber/InternalSerialNumber: preserved
```

Expected container and preview changes:

- `DNGVersion` changed from `1.4.0.0` to `1.7.0.0`.
- `DNGBackwardVersion` changed from `1.1.0.0` to `1.7.0.0`.
- `Software` and XMP creator tags changed to Adobe DNG Converter.
- Preview and thumbnail images were regenerated.
- `NewRawImageDigest` changed, as expected after rewriting the raw image data.

For lossy `d=0.05`, Adobe DNG Converter changed the stored main image state:

```text
SubIFD ImageWidth: 9600 -> 9552
SubIFD ImageHeight: 6376 -> 6360
WhiteLevel: 14848 14848 14848 -> 65535 65535 65535
```

That makes the lossy ADC output a different image state from the original
PixelShift2DNG file. It may still be valid and useful, but it must be compared
through a controlled render pipeline rather than treated as a direct
drop-in-compression change.

Follow-up local tests on a larger PixelShift16 batch found another important
detail: ADC lossy DNG/JXL files may include `OpcodeList2` `MapPolynomial`
entries on the main LinearRaw IFD. A raster-level comparison that decodes the
JXL tiles, divides by `WhiteLevel`, and stops there reports a large false
domain mismatch. Applying the `OpcodeList2` polynomial maps after linear
reference normalization brings the same crops back into the expected error
range and restores the expected ordering between `d=0.03`, `d=0.05`, and
`d=0.10`.

Use:

```powershell
python scripts\run_dng_jxl_verification.py --scan-root "D:\scan-tests\batch"
```

for DNG-raster smoke checks. This is still not a substitute for rendering
through RawTherapee, Adobe Camera Raw, Lightroom, FilmLab, or another practical
film workflow; it only makes the low-level DNG/JXL comparison respect the DNG
opcode processing model.

## RawTherapee Compatibility Probe

On 2026-08-29, RawTherapee 5.12 CLI was tested with the fixed project profile
against one lossless ADC DNG/JXL and the matching lossy `d=0.05` candidate.
Both attempts stopped at file loading with:

```text
Error loading file: <ADC candidate>.dng
```

The source PixelShift2DNG files are already rendered by the same project
workflow. This establishes a concrete incompatibility in the current
RawTherapee 5.12 path; it does not show that the embedded JPEG XL codestream is
corrupt. It means RawTherapee cannot currently provide the controlled
source-versus-ADC same-render comparison required by this project.

## What This Changes

This established a practical off-the-shelf conversion path:

```text
PixelShift2DNG DNG -> Adobe DNG Converter -> DNG 1.7 with internal JPEG XL
```

The later verification work did not promote it to the primary candidate. Lossy
ADC output changed geometry, `WhiteLevel`, and opcode-dependent sample
interpretation, while RawTherapee 5.12 could not load the generated DNG/JXL
files. The current break-even study therefore uses standalone `.jxl` made from
one declared PS16 rendered state. These ADC findings are retained as a closed
compatibility investigation, not as an unfinished release task.
