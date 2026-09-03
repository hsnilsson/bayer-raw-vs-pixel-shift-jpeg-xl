# muimg DNG/JXL Feasibility Probe

This bounded probe asks whether `muimg` can encode the existing PixelShift2DNG
main image as JPEG XL without the geometry and sample-domain rewrites observed in
the Adobe DNG Converter lossy path.

It is deliberately not a second full study. One approved resolution-target frame
was used to answer four narrower questions:

1. Is lossless output pixel-exact?
2. Where does stored size cross the paired 61 MP RAW size?
3. Are the source DNG geometry, white level, color metadata, and photographic
   EXIF retained?
4. Can current applications open the result?

## Input And Method

- Tool: `muimg 0.1.20260718.1648`, effort `7`
- PS16 source: Adox high-resolution black-and-white test target,
  `_DSC6582-_DSC6597.dng`
- Paired single-shot baseline: `_DSC6577.ARW`, 66.72 MiB
- Source PS16 DNG: 669.83 MiB, 19200 x 12752 x 3 stored samples
- Four 768 x 768 review crops from the existing Adox crop plan
- Color: 64 x 64 patch means, including the deterministic hard
  negative-density stress transform
- Structure: candidate-minus-reference high-pass RMS divided by reference
  high-pass RMS, radius 2

The generated DNG files and decoded working rasters remain local on `D:`. Only
the image-free aggregate record in
`metadata/muimg_dng_jxl_probe.json` is retained in Git.

The essential commands were:

```powershell
python -m venv D:\jpegxl-muimg-tools\venv
D:\jpegxl-muimg-tools\venv\Scripts\python.exe -m pip install muimg==0.1.20260718.1648

D:\jpegxl-muimg-tools\venv\Scripts\muimg.exe dng copy `
  <source-ps16.dng> <candidate.dng> `
  --jxl-distance 0.07 --jxl-effort 7 --preview --preview-reduce 8

python scripts\run_dng_jxl_verification.py `
  --scan-root <verification-root> `
  --source _DSC6582-_DSC6597 `
  --level d007 `
  --crop-plan results\break_even_crop_guides\crop_plan.json `
  --crop-case "adox_vlad_resolution_target|_DSC6577" `
  --patch-size 64 --patch-color-space srgb --maxworkers 4
```

`verification-root` follows the existing project convention: the source DNG is
at its root and the candidate is under
`adc_jxl_dng/d007/_DSC6582-_DSC6597.dng`. The directory name is historical; the
verifier itself is encoder-independent.

## Result

Lossless output was exact across 734,515,200 16-bit channel samples: zero changed
samples, zero maximum error, and matching decoded-pixel SHA-256 hashes. It was
574.43 MiB, or 85.8% of the source PS16 DNG, but far above the 66.72 MiB RAW61
budget.

| Candidate | MiB | % of RAW61 | Hard-density patch p95 DeltaE00 | Mean / worst normalized structure error |
| --- | ---: | ---: | ---: | ---: |
| d003 | 87.60 | 131.3% | 0.0816 | 0.2310 / 0.3746 |
| d005 | 87.60 | 131.3% | 0.0816 | 0.2310 / 0.3746 |
| d006 | 73.46 | 110.1% | 0.0912 | 0.2688 / 0.4368 |
| d007 | 61.58 | 92.3% | 0.1020 | 0.3103 / 0.4980 |
| d007 plus generated preview | 63.09 | 94.6% | 0.1020 | 0.3103 / 0.4980 |
| d010 | 42.46 | 63.6% | 0.1219 | 0.3957 / 0.6544 |
| d022 | 21.79 | 32.6% | 0.2065 | 0.4931 / 0.8075 |
| d025 | 19.80 | 29.7% | 0.2272 | 0.5032 / 0.8176 |

On this input, d003 and d005 produced different container bytes but the same
encoded size and measured crop values, indicating the same effective
quantization result for the sampled content.

For this frame, the storage crossing is between d006 and d007. The d007 file
with a generated 2390 x 1592 preview is the more practical probe artifact. Its
entire encoded main image is byte-identical to d007 without a preview; only the
container layout and preview were added.

The color and structure figures above are codec-only measurements against the
PS16 source in camera-linear DNG sample space. They show a small mean-color shift
and increasing fine-structure mismatch as compression rises. They must not be
divided directly by the main report's RAW61 values: those are measured after a
RawTherapee render and registration, in a different processing domain.

Embedded-codestream inspection found the lossless main image on the
original-profile/non-XYB path. Four d007 tiles spread across the 3,750-tile main
image all used XYB. Lossy muimg is therefore still a perceptually transformed
JPEG XL path, not direct lossy preservation of the camera-linear channel numbers.
That makes the negative-density stress results relevant even though muimg avoids
the ADC geometry and white-level rewrites.

## Metadata Audit

The checked source and d007-preview candidate retained the stored main-image
shape, active area, default crop, `WhiteLevel`, both color matrices,
`AsShotNeutral`, camera identity, lens model, exposure settings, and capture
time. The EXIF fields were relocated from an EXIF IFD into IFD0, not erased.

Four non-preview semantic tags were absent:

- `ExifVersion`: descriptive and copyable, but its absence is avoidable.
- `NoiseReductionApplied`: processing-history metadata; copyable only if its
  meaning remains true after the rewrite.
- `RawDataUniqueID`: should describe the resulting raw image data, so blindly
  copying the source value onto a lossy candidate would be misleading.
- `NewRawImageDigest`: an integrity digest of raw image data; it should be
  recalculated for the output rather than copied.

`YCbCrCoefficients` and `YCbCrPositioning` disappeared with the replaced source
preview. The generated preview has its own valid layout.

## Compatibility

| Application | Local result |
| --- | --- |
| Adobe DNG Converter 18.5 | Accepted d007 and produced another DNG |
| RawTherapee 5.12 | `Error loading file` |
| darktable local build | rawspeed reported `No RAW chunks found` |

Adobe acceptance confirms that at least one independent DNG implementation can
parse the file. It does not prove equivalent rendering throughout Adobe software.
The RawTherapee and darktable failures are operational blockers for this
project's current same-render pipeline, not evidence that the encoded pixels are
damaged.

## Interpretation

This probe materially improves the DNG/JXL outlook: unlike the tested lossy ADC
path, muimg preserved the checked geometry, white level, and color metadata while
crossing below the paired RAW61 storage budget on one frame. It therefore earns
a documented candidate status.

It does not replace the current standalone-rendered-JXL result or justify deleting
source DNGs. A decision-grade claim still needs multiple film frames and a trusted
DNG/JXL renderer that can process source and candidate through equivalent color,
inversion, and grading stages.
