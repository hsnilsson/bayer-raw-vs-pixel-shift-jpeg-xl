# Publication Summary

This repository is a work-in-progress public research package about JPEG XL,
PixelShift, and camera scanning of film.

## The Question

The project asks:

> At the same storage budget, can a better-sampled high-resolution PixelShift
> image stored as conservative JPEG XL preserve more useful film information
> than a lower-resolution raw capture?

This is not the same as asking whether lossy JPEG XL is identical to raw. It is
not. The project is about a practical storage tradeoff: sampling more of the
film frame versus preserving every numeric value from a smaller capture.

## What Is In The Repo

- A public, reproducible JPEG XL latitude-stress pipeline.
- Public FADGI/OpenDICE and Library of Congress TIFF test images tracked through
  Git LFS.
- A clear separation between public reproducible evidence and private local
  PixelShift scan evidence.
- Source sidecars and manifests for downloaded public test data.
- Selected public visual panels comparing JPEG XL `d=0.05` and `d=0.10`.
- A publication-safety audit and a combined readiness check.
- Cautious conclusions and limitations.

For prior-art and project-positioning context, see:

- [RELATED_WORK.md](../RELATED_WORK.md)
- [RESEARCH_PLAN.md](../RESEARCH_PLAN.md)

## Current Practical Result

The current practical result is:

- Keep DNG/RAW/lossless originals when possible.
- JPEG XL lossless can preserve a chosen 16-bit rendered/extracted state
  exactly, but the tested storage savings were modest.
- JPEG XL `d=0.05` remains the most interesting conservative lossy candidate.
- JPEG XL `d=0.10` looks too aggressive for an archival claim without stronger
  evidence.

The best-supported public result is the v2 latitude-stress test:

- [docs/public-latitude-v2.md](public-latitude-v2.md)

The easiest public reading order is:

- start with the LOC Golden Gate figures, because they make the diagnostic
  difference panels easiest to understand
- use the FADGI/OpenDICE negative target as the reproducibility anchor
- use the LOC Wildflowers figures as the fine-texture stress case

For the fastest overview of how public FADGI/OpenDICE tests, private scan tests,
and pending storage-budget claims relate to each other, see:

- [FINDINGS.md](../FINDINGS.md)

## What This Does Not Prove

This does not prove that lossy JPEG XL should replace raw/DNG masters.

It does not prove that `d=0.05` survives all real film-negative workflows.

It does not yet answer the core sampling question directly, because that needs
anonymous real negatives or a controlled 61 MP raw versus 240 MP PixelShift test.

## How To Check The Repo

Run:

```powershell
python scripts\check_publication_ready.py
```

For the full reproduction path, see:

- [REPRODUCIBILITY.md](../REPRODUCIBILITY.md)

## Suggested Framing When Sharing

A cautious public framing:

> This is a reproducible investigation into whether conservative JPEG XL can
> make high-resolution PixelShift camera scanning practical under real storage
> constraints. The early evidence suggests `d=0.05` is worth further testing,
> while `d=0.10` looks too aggressive. This is not a recommendation to delete
> raw/DNG originals.

## Feedback Wanted

Useful critique would include:

- better negative-inversion stress tests
- better public or shareable real-negative test material
- problems in the metrics or transforms
- color-management concerns
- metadata preservation concerns
- evidence for or against the PixelShift sampling hypothesis
