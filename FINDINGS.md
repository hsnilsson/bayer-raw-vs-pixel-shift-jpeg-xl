# Findings

This page is the shortest map of what the project has found, what each evidence
track is allowed to prove, and what still remains open.

## Core Question

At the same storage budget, can a better-sampled PixelShift camera scan stored
as conservative JPEG XL preserve more useful film information than a lower
resolution raw capture?

This is not the same as claiming that lossy JPEG XL is identical to raw. It is
an archive tradeoff question: sampling more of the film frame versus preserving
every numeric value from a smaller capture.

## Evidence Tracks

| Track | Data | What It Helps Answer | What It Does Not Answer |
| --- | --- | --- | --- |
| Public latitude stress | FADGI/OpenDICE TIFFs and Library of Congress TIFFs | Whether JPEG XL distance settings behave predictably under reproducible tone/negative-like stress | Whether PixelShift 16 beats 61 MP raw on real camera-scanned film |
| Private DNG/JXL scan tests | Kodak Gold 200-5 and Kodak Safety Film 5035 PixelShift2DNG scans | How Adobe DNG Converter DNG/JXL behaves on real local color-negative camera scans | Public reproducibility, because the source scans are private |
| Patch-color diagnostics | Local DNG/JXL verification crops | Whether lossy JXL changes local mean color or mostly changes pixel texture/noise | Absolute scene color accuracy or a full color-managed film-rendering result |
| Local scan-study runner | Ignored `input/` scan folders | Repeatable intake and verification for future private/anonymized scans | New scientific evidence by itself |
| Storage-budget comparison | Still pending | The main project hypothesis: 61 MP raw versus 240 MP PixelShift 16 JXL at similar retained size | Not answered yet |

## What Happened To FADGI/OpenDICE

The FADGI/OpenDICE files are still part of the project. They are used in the
public, reproducible test track, not in the private local scan queue.

Current public pipeline:

```powershell
python scripts\run_public_latitude_v2.py --publish-figures
```

This uses public FADGI/OpenDICE targets together with Library of Congress TIFFs.
Those files are good for a shareable stress test because other people can run
the same data and inspect the same figures.

They should not be treated as replacements for real camera-scanned negatives.
Their job is to make the codec/stress methodology public and reproducible while
the private film scans develop the real workflow.

## Current Pattern

Across the current public and private evidence, the ordering is stable:

- lossless JPEG XL can preserve the chosen image state exactly
- `d=0.03` is the cleaner conservative lossy candidate
- `d=0.05` is the stronger storage compromise
- `d=0.10` is consistently riskier, especially after hard negative-like stress

The new patch-color tests add an important nuance: `d=0.03` and `d=0.05` can
show very low local mean-color `DeltaE00` while still showing larger pixel-level
RMSE after negative-like transforms. That suggests the main lossy penalty may
often be texture/noise/detail change rather than broad local color bias.

That is encouraging, but it is not enough to recommend lossy JXL as the only
master.

## Best Current Recommendation

For irreplaceable work, keep original raw/DNG/lossless masters when possible.

Treat conservative JPEG XL, especially `d=0.03` and `d=0.05`, as promising
experimental or secondary master candidates until the storage-budget and
color-managed render tracks are complete.

## What Would Make This Strong

The project becomes much more useful when these pieces are all represented:

- public/reproducible FADGI/OpenDICE stress results
- anonymized real negative examples
- fully color-managed render/export comparison
- metadata and ICC preservation checks
- direct 61 MP raw versus 240 MP PixelShift 16 JXL storage-budget comparison
- selected crops showing where PixelShift preserves more real film structure

The existing local runner is meant to make the next real-negative additions
routine: add scan folder, generate/refresh manifest, create ADC candidates, run
the local study queue, then update the public-facing summary only with safe or
anonymized material.
