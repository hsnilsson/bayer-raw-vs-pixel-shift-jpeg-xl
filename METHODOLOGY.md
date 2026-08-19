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

#### Why XYB Requires A Post-Inversion Test

Lossy JPEG XL commonly converts linear RGB to the perceptual, opponent-color
XYB space before transform coding and quantization. The encoder then spends bits
according to the visual appearance of the image being encoded. For a film scan,
that image is still the orange-masked, low-contrast negative; the encoder does
not know which variations a later negative conversion will expand. The libjxl
[architecture overview](https://github.com/libjxl/libjxl/blob/main/doc/xl_overview.md)
describes the linear RGB to XYB path and its perceptually guided adaptive
quantization. Its
[format overview](https://github.com/libjxl/libjxl/blob/main/doc/format_overview.md)
also distinguishes XYB data from data stored in the original color profile.

The distinction is not that a simple inversion inherently magnifies error. If
`p = 1 - n`, then an input error `epsilon` becomes `-epsilon`: its absolute size
is unchanged. Real negative processing is more demanding. Per-channel film-base
normalization, orange-mask removal, white balance, and steep tone curves can all
apply gains greater than one. Density conversion is especially relevant:

```text
D = -log(T)          |dD/dT| = 1/T
```

At low transmittance, a small error in `T` can therefore become a much larger
density error. Clipping can also move nearly equal reference and candidate
values to different sides of a hard boundary. This is a mismatch between the
domain used for the lossy decision and the domain in which the archived image
will later be judged; it is not evidence that XYB is defective or that the same
risk is unique to JPEG XL.

For every lossy track, record the actual internal path when the available tools
expose it:

- VarDCT or Modular mode
- original-profile or XYB color path (`uses_original_profile` in libjxl)
- signaled primaries and transfer function
- source ICC profile or declared input color encoding
- decoder output profile and bit depth

For DNG files with embedded JPEG XL, inspect a representative segment (tile or
strip) from each JXL-compressed IFD:

```powershell
python scripts\inspect_dng_jxl_color_path.py "D:\scan-tests\candidate.dng"
```

The helper copies only the selected compressed segment to a temporary directory,
runs `jxlinfo`, reports the header and inferred path, and deletes the temporary
copy. It does not decode or publish image pixels. Multiple representative
segments must still be checked before treating a per-file result as uniform.

When comparing Adobe DNG Converter lossy DNG/JXL output at the DNG raster level,
apply DNG processing tags that change the decoded linear-reference domain before
measuring pixel differences. In current ADC lossy output this includes
`OpcodeList2` entries such as `MapPolynomial`; per the DNG opcode model,
`OpcodeList2` is applied after mapping the raw image to linear reference values,
and `MapPolynomial` stores coefficients in increasing degree order. The local
helper for this track is:

```powershell
python scripts\run_dng_jxl_verification.py --scan-root "D:\scan-tests\batch"
```

The script extracts matched active-crop windows, normalizes by each file's
`WhiteLevel`, applies supported `OpcodeList2` `MapPolynomial` entries, and then
runs the same identity and negative-density stress metrics used elsewhere in
the project. A raw decoder comparison that skips these opcodes is a useful
diagnostic, but it is not a fair quality metric for ADC lossy DNG/JXL.

By default the verifier also writes patch-based color diagnostics:

- `patch_metrics.csv`
- `patch_summary.csv`
- `patch_luminance_summary.csv`
- `patch_chroma_summary.csv`

For each crop and transform, the script divides the image into fixed patches,
averages each patch in a declared linear RGB comparison space, converts the
patch mean to XYZ and Lab, and then computes CIEDE2000 (`DeltaE00`) between the
reference and candidate patch means. This is intentionally different from
averaging Lab values per pixel.

These patch metrics answer a narrower question than the pixel metrics: did the
candidate keep the same local mean color, or did it introduce a systematic
color bias? The script still records pixel RMSE/PSNR and patch variation because
JPEG XL may change grain/noise while preserving the mean patch color. The
`error_to_ref_luma_std` diagnostic compares compression error with the
reference patch's own luminance variation; it is useful for ranking cases, but
it is not a perceptual standard.

The default comparison RGB space is `srgb`. This is a declared analysis space
for comparing the reference and candidate inside the same controlled pipeline,
not a claim that the DNG raster is an absolute sRGB rendering of the film.
Future renderer-based tests should use the actual exported ICC/profile space
when interpreting `DeltaE00`.

Full patch JSON can be written with `--patch-json`, but CSV is the default to
avoid duplicating large patch tables.

Two diagnostic controls would isolate this mechanism more directly:

1. Compare XYB with original-profile/no-color-transform encoding at a matched
   file size, where the encoder API supports both paths.
2. Compare `encode negative -> decode -> invert` with `invert losslessly ->
   encode positive` at a matched file size. The second path is not a proposed
   negative master; it tests whether optimizing the wrong visual state accounts
   for part of the post-inversion error.

The main archive test must still apply one fixed transform, with parameters
estimated from the reference, to both reference and candidate. A separate
end-to-end test may let the inverter estimate each image independently to reveal
whether codec error also destabilizes automatic film-base or color estimation.

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

For primary storage-budget comparisons, the single-shot baseline should be a
normal camera single-shot ARW. Sony PixelShift `1/1` captures may be retained as
secondary controls because they are still single Bayer raw frames, but they must
be labeled separately when they are stored as uncompressed RAW rather than the
normal compressed single-shot format.

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
- patch mean `DeltaE00`
- patch mean channel bias
- patch noise/error diagnostics
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
