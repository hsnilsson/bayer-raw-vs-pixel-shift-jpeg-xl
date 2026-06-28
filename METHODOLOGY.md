# Methodology

This project compares archival choices for camera-scanned film under realistic
storage constraints.

## Core Principle

Compare equivalent image states.

For raw-like files such as DNG or ARW, render each file through the same trusted
pipeline before comparing pixels. For JPEG XL, decode with a known decoder and
compare the decoded pixels with the same rendered reference.

## Test Tracks

### 1. Lossless Round Trip

Purpose: prove whether the chosen extraction/rendering state survives JPEG XL
lossless encode/decode exactly.

Typical chain:

```text
DNG or TIFF reference -> PNG/TIFF 16-bit state -> cjxl -d 0 -> djxl -> pixel compare
```

Expected result for true lossless: exact match, maximum error 0, MAE 0.

### 2. Lossy Matrix

Purpose: measure how JPEG XL distance settings affect file size and pixel error.

Candidate distances:

- `0.03`
- `0.05`
- `0.10`
- `0.20`
- `0.30`

The conservative candidate after private exploratory tests is currently `0.05`.

### 3. Latitude Stress

Purpose: test whether small compression errors become larger after operations
similar to negative inversion and strong film editing.

Operations should include:

- channel-wise color balance
- inversion or negative-like transform
- curve/contrast expansion
- shadow lifting
- highlight compression
- wide-gamut 16-bit output

This track should be automated outside FilmLab so it can be reproduced.

Current public script:

```powershell
python scripts\run_public_latitude_v2.py --publish-figures
```

The wrapper runs `scripts/run_public_latitude_stress.py` on the current public
test set, then runs `scripts/make_public_crop_panels.py`. The lower-level stress
script uses deterministic crops, JPEG XL distance settings, and several hard
transforms: identity, shadow push, steep curve, percentile-based negative
stretch, simple negative grade, and newer density-based negative-print
transforms.

The density transforms estimate per-channel film base and black points from the
reference crop, convert scan values to approximate transmittance, map
transmittance to density with `-log(transmittance)`, then apply print-like
contrast curves.

Create visual panels from a result directory:

```powershell
python scripts\make_public_crop_panels.py results\public_latitude_stress_v2
```

### 4. FilmLab Reality Check

Purpose: test a practical film-inversion workflow.

Known caveat: FilmLab 3.5.0 appeared to render direct lossy JXL imports with a
different color interpretation. The measured private test therefore used:

```text
JXL -> djxl -> 16-bit PNG with original ProPhoto ICC -> FilmLab -> 16-bit ProPhoto TIFF
```

### 5. Sampling Quality

Purpose: compare lower-resolution raw capture with higher-resolution PixelShift
capture as digital representations of the film original.

Recommended tools:

- FADGI/OpenDICE target analysis
- AutoSFR or equivalent spatial-frequency testing
- visual crops of grain, dye clouds, edges, and fine texture

## Metrics

At minimum:

- file size and percent of reference DNG size
- exact match
- maximum absolute error
- MAE
- RMSE
- PSNR
- per-channel MAE and bias
- p95/p99/p99.9 pixel maximum error

Visual review should use crops from:

- fine grain or dye clouds
- skin tones or organic color transitions
- dense shadows
- near-clipped highlights
- dust, scratches, and hard edges

## Reproducibility Rules

- Record tool versions.
- Record encoder settings.
- Keep source URLs and rights notes for public test data.
- Store SHA-256 hashes for downloaded and generated public test files.
- Separate verified measurements from interpretation.
