# Limitations

This project is intentionally cautious. The current evidence is useful, but it
does not yet prove a universal archival rule.

## Current Limitations

- Local exploratory images require an explicit publication decision. Selected
  derived panels may be published when owner-approved; full-size source scans
  require a separate data-publication decision.
- Most numerical results currently come from a small number of images.
- FilmLab is not a fully controlled scientific transform.
- FilmLab 3.5.0 appeared to mishandle direct lossy JXL color-profile import in
  one test.
- A rendered PixelShift2DNG file is not the same as the original camera ARW
  sequence.
- PixelShift2DNG output is already demosaiced/merged and cannot preserve every
  property of the original sensor captures.
- JPEG XL visual distance is optimized for perception, not for future arbitrary
  negative-inversion edits.
- The current ADC color-path check inspected only representative embedded JXL
  tiles from a small local lossless/lossy file set; it must be broadened before
  claiming that all ADC-generated lossy `LinearRaw` DNGs use the same XYB path.
- Standard image metrics do not directly measure archival value.
- A public target test can measure capture quality but cannot fully represent
  organic film grain, dye clouds, or real negatives.

## What This Does Not Prove

It does not prove that lossy JPEG XL is universally safe as the only archive
master.

It does not prove that `d=0.05` is always visually transparent after inversion.

It does not prove that PixelShift is always better than single-shot raw. Movement,
registration errors, lens limits, diffraction, and lighting can all erase the
advantage.

## What Would Strengthen The Case

- Repeat tests on public test images.
- Repeat tests on newly photographed anonymous negatives.
- Add FADGI/OpenDICE measurements.
- Add an automated FilmLab-independent latitude stress test.
- Add blind visual comparisons.
- Publish crops and diff panels.
- Document tool versions and commands for every result.
