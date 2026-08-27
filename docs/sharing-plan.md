# Sharing Plan

This project should be shared as a cautious public investigation, not as an
archive recommendation.

## Current Public Shape

Best current framing:

> A reproducible investigation into whether conservative JPEG XL can make
> high-resolution PixelShift camera scanning practical under real storage
> constraints.

Lead with the storage tradeoff:

```text
61 MP single-shot raw
versus
240 MP PixelShift 16 stored as conservative JPEG XL
```

Then be explicit that the direct same-budget answer is now a preliminary local
result, not a general archival recommendation.

## What Can Be Shared Now

- public FADGI/OpenDICE and Library of Congress latitude-stress results
- source sidecars and rights notes for public test images
- JPEG XL lossless/exactness results for chosen rendered states
- evidence that `d=0.03` and `d=0.05` are more plausible than `d=0.10`
- the local workflow code, without automatically publishing full-size scan files
- selected owner-approved real-negative review panels
- the metadata-diff and patch-color methodology
- the limitation that ADC lossy DNG/JXL changes stored shape, crop origin,
  `WhiteLevel`, and `OpcodeList2` in current local tests

## What Should Not Be Claimed Yet

- that lossy JPEG XL can replace DNG/RAW masters generally
- that Adobe DNG Converter lossy JXL DNG is safe as a sole master
- that `d=0.05` survives all negative inversion workflows
- that PixelShift 16 JXL generally beats 61 MP raw at the same storage budget
- that public FADGI/OpenDICE TIFF tests prove real camera-scanned film behavior

## Recommended First Post

Use a short GitHub-first post:

1. State the practical problem: camera scanning plus PixelShift creates too much
   data for many real archives.
2. State the hypothesis: a better-sampled image with careful JPEG XL may retain
   more useful film information under a fixed storage budget.
3. Show the public latitude v2 figures, leading with the LOC Golden Gate panels.
4. Explain the Kodak tests as owner-approved local workflow evidence, with only
   selected derived panels published unless source-data publication is decided.
5. Ask for critique on methodology, metrics, color management, DNG/JXL handling,
   and better public negative test material.

## Suggested Venues

- GitHub README/issues for reproducibility feedback
- JPEG XL community for codec and encoder-setting critique
- camera-scanning or film-digitization forums for workflow critique
- preservation/digitization communities only after the storage-budget and target
  measurement tracks are represented more strongly

## What Would Make It Stronger

- more owner-approved or anonymized real-negative examples
- one full 61 MP raw versus 240 MP PixelShift 16 JXL storage-budget comparison
- a target capture with OpenDICE, AutoSFR, or similar measurement
- a FilmLab-independent renderer/inversion stress test
- direct comparison of ADC JXL DNG and standalone JXL from the same reference
  image state
