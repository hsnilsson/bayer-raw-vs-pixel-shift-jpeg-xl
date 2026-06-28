# Next Steps

This file tracks what remains after the current public-test cleanup.

## Ready Without New Private Material

- Run `python scripts\check_publication_ready.py` before sharing.
- Run a clean-clone reproduction test on another machine or in another folder.
- Large public TIFF files are intended to be committed through Git LFS.
- Review the selected v2 public figures in `docs/figures/` and remove any that feel
  too noisy, redundant, or visually confusing.
- The first smoke-test page is archived under `docs/archive/`; v2 is the main
  public result.

## Needs New Or Anonymized Test Material

- Add anonymous real color-negative camera scans.
- Add crops that intentionally stress skin tones, dense shadows, smooth color
  transitions, film grain or dye clouds, dust, scratches, and hard edges.
- Repeat the `d=0.03`, `d=0.05`, and `d=0.10` tests on those scans.
- Add a direct 61 MP single-shot raw versus 240 MP PixelShift comparison at a
  similar storage budget.

## Needs Human Judgment

- Confirm the third-party-data rights posture before publishing bundled images
  or generated figures.
- Decide how strongly the public README should frame the hypothesis: cautious
  technical note, active research project, or community challenge.
- Decide where to share first: GitHub only, scanning forum, JPEG XL community,
  photography forum, or a short blog-style writeup.

## Research Questions Still Open

- Does `d=0.05` remain visually acceptable after realistic film inversion and
  grading on real negatives?
- Does PixelShift 16 preserve visibly more useful film structure than 61 MP raw
  at the same storage budget?
- Are JPEG XL errors more objectionable in particular film stocks, exposure
  ranges, or color channels?
- Which metadata must be preserved manually if DNG is not the long-term master?
- Do common editing tools handle JXL color profiles consistently enough for this
  workflow?
