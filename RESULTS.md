# Results

This page summarizes the current state of evidence. The project is still work in
progress. Early exploratory results came from private source images; the current
public latitude tests are reproducible from public data, but they do not yet
replace real anonymous color-negative camera-scan tests.

For the shortest interpretation of these results, see
[CONCLUSIONS.md](CONCLUSIONS.md).

## Private Exploratory Findings

### Adobe DNG Converter JPEG XL DNG Smoke Test

Adobe DNG Converter 18.5 accepted three local PixelShift2DNG files and rewrote
them as DNG 1.7 files with internal JPEG XL compression.

Lossless output reported `SubIFD Compression: JPEG XL`, `Photometric
Interpretation: Linear Raw`, and `JXLDistance: 0`. It preserved the main image
dimensions, crop size, black level, white level, color matrices, camera model,
lens model, and serial-number metadata checked with ExifTool. Previews were
regenerated and `Software`/XMP creator tags changed to Adobe DNG Converter.

| File | PixelShift2DNG | ADC lossless JXL DNG | Lossless % | ADC JXL DNG d=0.05 | d=0.05 % |
|---|---:|---:|---:|---:|---:|
| `private-scan-1.dng` | 173.54 MiB | 152.25 MiB | 87.7% | 88.41 MiB | 50.9% |
| `private-scan-2.dng` | 184.65 MiB | 157.83 MiB | 85.5% | 92.51 MiB | 50.1% |
| `private-scan-3.dng` | 145.80 MiB | 125.60 MiB | 86.1% | 83.95 MiB | 57.6% |

Important caveat: ADC lossy `d=0.05` changed the stored image state from
`9600 x 6376` with `WhiteLevel 14848` to the cropped `9552 x 6360` image with
`WhiteLevel 65535`. That output may still be useful, but it needs a fresh
controlled render and latitude-stress comparison.

A codestream-header check of the first two embedded tiles in one private file
pair also found that the lossless output used the original-profile/non-XYB path,
whereas the lossy `d=0.05` output used XYB. This makes post-inversion testing
relevant to the ADC path as well as external `.jxl`, but it is not yet a
multi-file or exhaustive tile result.

See [docs/adobe-dng-converter-jxl-dng-smoke-test.md](docs/adobe-dng-converter-jxl-dng-smoke-test.md).

### Kodak Gold 200-5 ADC DNG/JXL Batch

A private Kodak Gold 200-5 color-negative batch, shot in 1997, was scanned into
nine root-level PixelShift2DNG masters and converted with Adobe DNG Converter
to DNG 1.7 JPEG XL at the project-standard levels.

This is still private local evidence. Do not publish the image panels without
replacing or anonymizing the source material.

| Level | Total Size | Size vs PixelShift2DNG | Low-Level Result |
|---|---:|---:|---|
| PixelShift2DNG source | 3.65 GiB | 100.0% | reference |
| ADC lossless JXL DNG | 3.35 GiB | 91.9% | exact in tested crops |
| ADC JXL DNG `d=0.03` | 2.42 GiB | 66.4% | lowest tested lossy error |
| ADC JXL DNG `d=0.05` | 1.98 GiB | 54.3% | stronger storage candidate |
| ADC JXL DNG `d=0.10` | 1.35 GiB | 37.1% | visibly riskier stress level |

Across 45 crop windows and the scripted low-level transform set, lossless ADC
JXL DNG was exact: `MAE 0.00`, max error `0`, and infinite PSNR for every
transform. The lossy levels behaved monotonically:

| Level | Identity Mean MAE | Hard Negative-Print Mean MAE | Hard Negative-Print Worst MAE |
|---|---:|---:|---:|
| `d=0.03` | 8.59 | 133.60 | 217.07 |
| `d=0.05` | 14.70 | 230.43 | 380.10 |
| `d=0.10` | 28.24 | 468.69 | 760.71 |

The panel spot-checks matched the metric story: `d=0.05` can look very close in
identity comparisons, while aggressive negative-print transforms reveal
structured residual error in grain/density areas. `d=0.03` is cleaner but gives
up a substantial part of the storage win.

Three accidental `-(1)` PixelShift2DNG candidates in this batch had different
file bytes from their canonical root DNGs, but the decoded main image data and
key image metadata were identical. They were removed from the local input
folder after writing a private duplicate-comparison report.

Important caveat: this is a low-level DNG raster test that applies the known DNG
opcode handling. It is not a substitute for rendering through a practical film
workflow, visual review after real inversion/grading, or a public/anonymized
replication set.

### Lossless JPEG XL

Lossless JPEG XL round-tripped extracted 16-bit linear PixelShift2DNG image data
exactly in the tested files.

Interpretation: JPEG XL can preserve the chosen rendered/extracted pixel state
exactly when used losslessly.

### Lossless Size

Lossless JPEG XL saved only modest space compared with the tested PixelShift2DNG
files.

Interpretation: lossless JPEG XL is technically attractive but may not reduce
storage enough to justify replacing DNG masters.

### FilmLab ProPhoto Latitude Test

A private FilmLab test compared a lossless JPEG XL baseline with lossy JPEG XL
candidates after identical FilmLab inversion/export.

| JXL distance | Size vs selected DNG | MAE after inversion | PSNR after inversion |
|---:|---:|---:|---:|
| 0.03 | 60.7% | 279.7 | 43.73 dB |
| 0.05 | 49.8% | 285.4 | 42.46 dB |
| 0.10 | 33.9% | 558.9 | 36.90 dB |
| 0.20 | 19.8% | 952.3 | 32.72 dB |
| 0.30 | 13.2% | 1170.2 | 31.11 dB |

The FilmLab inversion amplified compression error by roughly 4.5 to 4.7 times
for distances 0.05 through 0.30.

Interpretation: negative inversion and strong tonal editing can expose or
amplify errors that are small before editing. Distance `0.05` is currently the
most interesting conservative lossy candidate, but it is not equivalent to a
lossless archive master.

## Current Practical Recommendation

Do not delete original DNG/RAW files based on the current evidence.

Working model:

- DNG/lossless master: safest per-pixel archive.
- JPEG XL lossless: exact but modest savings.
- JPEG XL `d=0.03`: cleaner conservative lossy candidate.
- JPEG XL `d=0.05`: promising compact secondary/working master candidate.
- JPEG XL `d=0.10`: more aggressive, needs stronger visual and numerical support
  before being considered archival.

The more interesting hypothesis is that a better-sampled PixelShift image stored
as conservative JPEG XL can preserve more relevant film information than a
lower-resolution raw capture at the same storage cost. That must be tested with
public, non-private images and physical targets.

## Public Latitude Stress v2

The second public run used 2048 px crops from six public TIFF images and added
density-based negative-print transforms. These transforms are a better scripted
proxy for the latitude-heavy edits that make color-negative workflows risky for
lossy compression.

Summary across the six public crops:

| Transform | JXL distance | Avg MAE | Avg PSNR | Avg p99 pixel max error | Avg encoded crop |
|---|---:|---:|---:|---:|---:|
| identity | 0.03 | 30.17 | 60.68 dB | 311.8 | 3.94 MiB |
| identity | 0.05 | 42.12 | 58.30 dB | 389.7 | 3.22 MiB |
| identity | 0.10 | 65.36 | 55.24 dB | 522.8 | 2.40 MiB |
| negative density hard print | 0.03 | 53.87 | 50.81 dB | 1185.1 | 3.94 MiB |
| negative density hard print | 0.05 | 77.06 | 48.45 dB | 1607.7 | 3.22 MiB |
| negative density hard print | 0.10 | 118.32 | 45.55 dB | 2188.9 | 2.40 MiB |

Interpretation: `d=0.10` is consistently worse than `d=0.05`, especially in
high-percentile errors after density-style transforms. `d=0.05` remains the most
interesting conservative lossy candidate, while `d=0.03` is the cleaner but
larger option.

Selected figures and full notes are in
[docs/public-latitude-v2.md](docs/public-latitude-v2.md).

## Archived Smoke Test

The first public smoke test is kept only as project history in
[docs/archive/public-smoke-test.md](docs/archive/public-smoke-test.md). The v2
density-based latitude stress test above is the current public result.
