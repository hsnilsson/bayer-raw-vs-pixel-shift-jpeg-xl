# Results

This page summarizes the current state of evidence. The project is still work in
progress. Early exploratory results came from private source images; the current
public latitude tests are reproducible from public data, but they do not yet
replace real anonymous color-negative camera-scan tests.

For the shortest interpretation of these results, see
[CONCLUSIONS.md](CONCLUSIONS.md).

## Private Exploratory Findings

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
