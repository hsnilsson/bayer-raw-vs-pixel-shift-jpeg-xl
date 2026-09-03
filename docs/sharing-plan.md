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
- the standalone-JXL storage crossing between `d022` and `d025` on the current
  local material
- the local workflow code, without automatically publishing full-size scan files
- selected owner-approved real-negative review panels and small context
  thumbnails with crop boxes
- the metadata-diff and patch-color methodology
- the limitation that ADC lossy DNG/JXL changes stored shape, crop origin,
  `WhiteLevel`, and `OpcodeList2` in current local tests

## What Should Not Be Claimed Yet

- that lossy JPEG XL can replace DNG/RAW masters generally
- that Adobe DNG Converter lossy JXL DNG is safe as a sole master
- that any tested lossy level survives all negative inversion workflows
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
   selected derived panels/context thumbnails published unless source-data
   publication is decided.
5. Ask for critique on methodology, metrics, color management, DNG/JXL handling,
   and better public negative test material.

## Suggested Venues

- GitHub README/issues for reproducibility feedback
- JPEG XL community for codec and encoder-setting critique
- camera-scanning or film-digitization forums for workflow critique
- preservation/digitization communities with the current limitations stated
  prominently

## Remaining Qualification

The report is publishable as a provisional study. Broader material, blinded
review, and independent reproduction would strengthen the claim but are not
missing implementation. See [NEXT_STEPS.md](../NEXT_STEPS.md) for the maintained
queue and [LIMITATIONS.md](../LIMITATIONS.md) for the scientific boundaries.
