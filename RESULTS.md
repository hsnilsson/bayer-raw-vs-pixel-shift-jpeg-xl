# Results

This page summarizes the current state of evidence. The project is still work in
progress. Early exploratory results came from local source images; the current
public latitude tests are reproducible from public data, but they do not by
themselves replace real color-negative camera-scan tests.

For the shortest interpretation of these results, see
[CONCLUSIONS.md](CONCLUSIONS.md).
For a clearer map of public, local, and still-pending claims, see
[FINDINGS.md](FINDINGS.md).

## Evidence Tracks At A Glance

| Track | Data | Current Role | Status |
|---|---|---|---|
| Public latitude stress | FADGI/OpenDICE and Library of Congress TIFFs | Reproducible codec/stress evidence and public figures | active public track |
| Local scan tests | Kodak Gold 200-5 and Kodak Safety Film 5035 PixelShift2DNG scans | Real workflow evidence for ADC DNG/JXL behavior on color-negative scans | selected derived panels are publishable with owner approval |
| Patch-color diagnostics | Matched DNG/JXL crop patches | Separates local mean-color bias from pixel texture/noise changes | implemented for local DNG/JXL verification |
| Storage-budget comparison | 61 MP raw versus 240 MP PixelShift 16 JXL | Direct test of the main hypothesis | active preliminary local result |

The FADGI/OpenDICE files are therefore not forgotten. They belong to the public
reproducibility track: they help show how the JPEG XL settings behave under a
standardized, shareable stress test. They do not replace the local film
scan track because they do not test PixelShift capture, PixelShift2DNG behavior,
or real film-frame sampling at 61 MP versus 240 MP.

## Local Exploratory Findings

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
relevant to the ADC path as well as external `.jxl`. The result is deliberately
limited to representative tiles and is not generalized to every ADC file.

See [docs/adobe-dng-converter-jxl-dng-smoke-test.md](docs/adobe-dng-converter-jxl-dng-smoke-test.md).

### Kodak Gold 200-5 ADC DNG/JXL Batch

A local Kodak Gold 200-5 color-negative batch, shot in 1997, was scanned into
paired PixelShift 4 and PixelShift 16 PixelShift2DNG masters. The current local
study focuses on the five PixelShift 16 masters, because that is the path most
relevant to the storage-budget question.

Selected derived review panels from this material are approved for publication.
Full-size source scans and generated outputs remain out of Git unless explicitly
promoted with a source/data publication decision.

| Level | Total Size | Size vs PixelShift2DNG | Low-Level Result |
|---|---:|---:|---|
| PixelShift2DNG source | 2.99 GiB | 100.0% | reference |
| ADC lossless JXL DNG | 2.78 GiB | 92.9% | exact in tested crops |
| ADC JXL DNG `d=0.03` | 2.00 GiB | 67.0% | lowest tested lossy error |
| ADC JXL DNG `d=0.05` | 1.63 GiB | 54.6% | stronger storage candidate |
| ADC JXL DNG `d=0.10` | 1.11 GiB | 37.0% | visibly riskier stress level |

Across 25 crop windows and the scripted low-level transform set, lossless ADC
JXL DNG was exact: `MAE 0.00`, max error `0`, and infinite PSNR for every
transform. The lossy levels behaved monotonically:

| Level | Identity Mean MAE | Hard Negative-Print Mean MAE | Hard Negative-Print Worst MAE |
|---|---:|---:|---:|
| `d=0.03` | 9.15 | 132.49 | 217.07 |
| `d=0.05` | 15.68 | 230.20 | 380.10 |
| `d=0.10` | 29.40 | 463.06 | 747.32 |

The panel spot-checks matched the metric story: `d=0.05` can look very close in
identity comparisons, while aggressive negative-print transforms reveal
structured residual error in grain/density areas. `d=0.03` is cleaner but gives
up a substantial part of the storage win.

A follow-up patch-color pass added fixed 256 px patch measurements. Each patch
was averaged in the declared linear RGB comparison space before conversion to
Lab and CIEDE2000 (`DeltaE00`). This separates local mean-color shifts from
pixel-level texture/noise changes.

| Level | Identity Median DeltaE00 | Hard Negative-Print Median DeltaE00 | Hard Negative-Print P95 DeltaE00 | Hard Negative-Print Max DeltaE00 | Hard Negative-Print Mean RGB RMSE |
|---|---:|---:|---:|---:|---:|
| `d=0.03` | 0.0035 | 0.0186 | 0.0459 | 0.0674 | 258.01 |
| `d=0.05` | 0.0034 | 0.0245 | 0.0568 | 0.0785 | 446.97 |
| `d=0.10` | 0.0033 | 0.0488 | 0.1161 | 0.1510 | 861.98 |

A smaller 64 px patch probe on two difficult frame groups raised the hard-print
patch values but did not change the ordering: median/max `DeltaE00` were
0.032/0.115 for `d=0.03`, 0.044/0.135 for `d=0.05`, and 0.090/0.333 for
`d=0.10`.

Interpretation: in this controlled raster/stress test, `d=0.03` and `d=0.05`
did not show large systematic local mean-color bias, even after the hard
negative-print transform. The main measured penalty remains pixel-level
error/texture change that becomes much larger after aggressive negative-like
processing. That is encouraging for color stability, but it is not the same as
proving lossy JXL safe as the only archive master.

The new metadata/ICC diff pass adds an operational caveat. After rational DNG
tag normalization, ADC lossless JXL DNG had no preservation-review metadata
changes in this active PixelShift 16 run. The ADC lossy JXL DNG candidates all
changed the stored raster shape, changed the active crop origin from `[8, 8]`
to `[0, 0]`, changed `WhiteLevel` from `14848` to `65535`, and added an
`OpcodeList2` `MapPolynomial`. The checked ICC/profile fields did not appear in
the diff. These changes may be valid Adobe DNG rewrite mechanics, but they must
be explained and render-tested before treating ADC lossy JXL DNG as a sole
master.

Three accidental `-(1)` PixelShift2DNG candidates in this batch had different
file bytes from their canonical root DNGs, but the decoded main image data and
key image metadata were identical. They were removed from the local input
folder after writing a private duplicate-comparison report.

Important caveat: this is a low-level DNG raster test that applies the known DNG
opcode handling. It is not a substitute for rendering through a practical film
workflow, visual review after real inversion/grading, or a public/anonymized
replication set.

### Kodak Safety Film 5035 ADC DNG/JXL Batch

A second local color-negative set, Kodak Safety Film 5035 shot in 1983, was
run through the same local DNG/JXL verification path for six PixelShift 16 DNG
masters. The local study runner now writes a cross-scan index under
`results/local_scan_study/`.

| Level | Total Size vs PixelShift2DNG | Identity Median DeltaE00 | Hard Negative-Print Median DeltaE00 | Hard Negative-Print P95 DeltaE00 | Hard Negative-Print Max DeltaE00 | Hard Negative-Print Mean RGB RMSE |
|---|---:|---:|---:|---:|---:|---:|
| ADC lossless JXL DNG | 92.9% | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| ADC JXL DNG `d=0.03` | 66.9% | 0.0021 | 0.0111 | 0.0748 | 0.2106 | 221.57 |
| ADC JXL DNG `d=0.05` | 55.4% | 0.0021 | 0.0129 | 0.1185 | 0.2975 | 377.44 |
| ADC JXL DNG `d=0.10` | 39.3% | 0.0023 | 0.0216 | 0.3843 | 0.5788 | 734.39 |

This second set repeats the same broad ordering as Kodak Gold: lossless is
exact, `d=0.03` is cleaner, `d=0.05` is the stronger storage compromise, and
`d=0.10` has a much worse tail after hard negative-print stress. Kodak5035 also
shows why tail metrics matter: median patch `DeltaE00` stays low even at
`d=0.05`, but p95/max values rise more than in the Kodak Gold set.

Its metadata/ICC diff repeated the Kodak Gold pattern: ADC lossless JXL DNG had
no preservation-review metadata changes after rational DNG tag normalization,
while lossy ADC JXL DNG changed stored raster shape, active crop origin,
`WhiteLevel`, and `OpcodeList2`.

Only the PixelShift 16 DNG masters in this folder had complete ADC JXL levels.
The PixelShift 4 root DNGs remain present locally but were not part of this
verification pass.

A follow-up header inspection on one Kodak Gold file and one Kodak5035 file
confirmed the expected ADC color-path split for representative main-image
segments: lossless ADC JXL DNG used the original-profile/non-XYB path for the
16-bit main image, while `d=0.05` used lossy XYB for the 16-bit main image.
Preview IFDs were lossy XYB even inside the lossless DNGs, which matters for
preview fidelity but not for the main-image preservation result.

### Standalone PS16 JPEG XL Storage-Budget Matrix

Because current raw editors cannot reliably treat ADC DNG/JXL candidates as the
same practical render input as the source PixelShift2DNG files, the direct
break-even path uses standalone JPEG XL made from a fixed 16-bit PS16 render:

```text
PixelShift2DNG PS16 -> RawTherapee neutral 16-bit TIFF -> cjxl -> djxl -> metrics
```

On the current local color-negative material, the median retained-size
break-even versus the paired 61 MP RAW baseline is between `d022` and `d025`.

| JXL level | Median size vs RAW61 | Current interpretation |
|---|---:|---|
| `d020` | 121.7% | still larger than RAW61 on median |
| `d022` | 106.4% | near the storage boundary but still larger on median |
| `d025` | 86.3% | first tested median level under budget; current diagnostics favor PS16 JXL |
| `d028` | 72.1% | under budget, needs visual review |
| `d030` | 69.7% | under budget, needs visual review |

`d100` and `d200` are deliberately aggressive visual stress references. They
are useful for showing what obvious codec damage looks like, but are excluded
from archive-candidate verdicts even when simple aggregate metrics look
favorable.

The current numeric summary is encouraging for the main hypothesis: the PS16 JXL
candidate remains much closer to the PS16 reference than the registered RAW61
render does in the current patch-color and high-pass structure metrics. The
important caveat is that the RAW61-vs-PS16 baseline may still include
render-profile, demosaic/acutance, and registration effects. Therefore these
numbers are a local break-even result, not a final recommendation to discard
RAW/DNG masters.

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
lower-resolution raw capture at the same storage cost. The current local
standalone-PS16 JXL matrix directly tests that tradeoff, but broader visual
review, more material, and independent reproduction are still needed before
making an archival recommendation.

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
