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

Several items from the original roadmap are now complete: the repository has a
FilmLab-independent latitude stress test, public FADGI/OpenDICE and Library of
Congress inputs, selected public comparison figures, and manifests that record
commands, code/input hashes, and tool versions. These results are documented in
[`docs/public-latitude-v2.md`](docs/public-latitude-v2.md). The public TIFFs test
codec and stress-transform behavior; they do **not** provide a paired 61 MP RAW
and 240 MP PS16 camera capture, so they cannot enter the core storage
break-even table as another film row.

### Prioritized Quick Wins

1. **Surface the existing public-image run in the web report.** Add a concise
   public reproducibility section with selected FADGI/OpenDICE and Library of
   Congress figures, the `d=0.03`/`0.05`/`0.10` results, and a link to the full
   manifest. This is mainly presentation work and makes already completed
   evidence visible without misrepresenting it as RAW61-versus-PS16 evidence.
2. **Add a blinded visual-review pass.** Randomize candidate labels and order in
   the existing crop viewer, collect per-crop choices, and reveal levels only
   after submission. This tests whether measured differences are practically
   detectable and reduces expectation bias.
3. **Turn the OpenDICE target from codec imagery into a target measurement.**
   Use its supplied reference/profile data with an appropriate target-analysis
   workflow to report color, tone response, noise, registration, and resolution
   where supported. Keep this separate from the break-even verdict: measuring
   the downloaded TIFF validates the analysis path, while photographing a
   physical target would validate the camera-scanning system.
4. **Add more anonymous negative captures to the paired matrix.** Prioritize
   difficult shadows, dense highlights, neutral/color patches, fine dye-cloud
   texture, and high-contrast edges. Each frame still needs matched RAW61 and
   PS16 captures; unrelated public TIFFs cannot substitute for that pairing.
5. **Capture a physical target as RAW61 and PS16.** This is the strongest target
   extension because it measures the sampling advantage and failure modes of
   the actual camera/lens/light/merge pipeline. It is valuable, but it requires
   new capture material and is therefore not a software-only quick win.

### Lower-Priority Extensions

- Repeat an application-specific inversion/export test when a stable,
  color-managed tool is chosen. Label it as that application's workflow rather
  than a universal negative-inversion result.
- Broaden the ADC embedded-JXL color-path audit only if ADC-in-DNG remains a
  practical archive candidate. Current application support and metadata/
  geometry changes make the standalone JXL path more relevant.
