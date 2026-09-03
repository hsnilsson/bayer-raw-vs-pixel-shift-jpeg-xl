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
| Local DNG/JXL scan tests | Kodak Gold 200-5 and Kodak Safety Film 5035 PixelShift2DNG scans | How Adobe DNG Converter DNG/JXL behaves on real color-negative camera scans | Full public reproducibility unless selected source data or review panels are published |
| Patch-color diagnostics | Local DNG/JXL verification crops | Whether lossy JXL changes local mean color or mostly changes pixel texture/noise | Absolute scene color accuracy or a full color-managed film-rendering result |
| Local scan-study runner | Ignored `input/` scan folders | Repeatable intake and verification for future private/anonymized scans | New scientific evidence by itself |
| Storage-budget comparison | Local standalone rendered-PS16 JXL matrix plus RAW61/structure metrics | The main project hypothesis: 61 MP raw versus 240 MP PixelShift 16 JXL at similar retained size | Still preliminary because the film corpus is limited and the visual review is neither blinded nor independently reproduced |

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
the local film scans develop the real workflow.

## Current Pattern

Across the older conservative-codec track, the ordering is stable:

- lossless JPEG XL can preserve the chosen image state exactly
- `d=0.03` is the cleaner conservative lossy candidate
- `d=0.05` is the stronger storage compromise
- `d=0.10` is consistently riskier, especially after hard negative-like stress
- Adobe DNG Converter lossless JXL DNG had no preservation-review metadata
  changes in the active PixelShift 16 local runs after rational DNG tag
  normalization; lossy ADC JXL DNG still changed stored shape, active crop
  origin, `WhiteLevel`, and `OpcodeList2`

The new patch-color tests add an important nuance: `d=0.03` and `d=0.05` can
show very low local mean-color `DeltaE00` while still showing larger pixel-level
RMSE after negative-like transforms. That suggests the main lossy penalty may
often be texture/noise/detail change rather than broad local color bias.

That is encouraging, but it is not enough to recommend lossy JXL as the only
master.

The standalone rendered-PS16 JXL path now produces candidates that cross below
the paired 61 MP raw storage budget on the current local material. The current
median size break-even is between `d022` and `d025`; `d025` through `d030`
compression are under budget in the automatic overview while still ranking as
PS16 JXL likely wins for the complete non-flagged pairs. This is useful local
evidence, not a final archival recommendation. Deliberately aggressive `d100`
and `d200` files remain available only as visual stress references and are not
counted as archive candidates.

## Best Current Recommendation

For irreplaceable work, keep original raw/DNG/lossless masters when possible.

Treat conservative JPEG XL, especially `d=0.03` and `d=0.05`, as promising
secondary or evaluation-master candidates, not as the only archive copy.

## What Would Make This Stronger

The repository already includes public stress inputs, owner-approved
real-negative crops, fixed color-managed rendering, metadata diagnostics, and a
direct 61 MP RAW versus 240 MP PS16 JXL storage comparison. The main remaining
ways to strengthen the claim are a broader film corpus, structured or blinded
visual review, independent reproduction, and a physical resolution-target
capture made with the same camera-scanning setup.

The local pipeline makes additional sets routine: add a scan folder, generate
or refresh its manifest, render the declared RAW61 and PS16 states, encode the
standalone JXL matrix, run the metrics, and publish only approved derived review
assets.
