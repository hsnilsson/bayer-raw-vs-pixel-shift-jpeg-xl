# Pixelshift Combiner Audit

## Question

Does PixelShift2DNG or Sony's ARQ combiner provide the fairer PS16 reference
for judging highlight separation and shadow recovery against a single-frame
RAW61 capture?

This audit is deliberately separate from the JPEG XL quality matrix. Changing
the Pixelshift combiner can change the rendered baseline, but it does not
change codec loss measured between a PS16 master and its decoded JPEG XL copy.

## Scope

The Adox results below use the historical **f/8** capture. On 2026-09-16 the
active local source was replaced by a new **f/4.5** capture with matching ARQ
and DNG masters, sequence `_DSC0001-_DSC0016`. This audit has not been rerun
with that replacement; its crop coordinates and scores must not be transferred
to the new sequence. See the
[current intake](local-scan-workflow.md#current-adoxvlad-target).

The local archive contained matching Sony ARQ and PixelShift2DNG outputs for two
exact 16-frame sequences:

- Adox high-resolution black-and-white test target: `_DSC6582-_DSC6597`, four
  approved 768 x 768 crops.
- Kodak Gold 200: `_DSC6798-_DSC6813`, one approved 768 x 768 crop.

Sony ARQ, PixelShift2DNG DNG, and the first ARW in each sequence were rendered
through RawTherapee 5.12 with the same repository neutral profile and 16-bit
TIFF output. The unpublished source files and full-size renders remain outside
the public site artifact.

Five crops from two sequences are enough to detect a consistent difference in
this material, not to establish a universal combiner ranking across cameras,
subjects, motion, or illumination.

## Normalization and measurements

For each crop the audit:

1. Registers the Sony ARQ render to the PixelShift2DNG render.
2. Upscales and registers the first source ARW as a common tonal anchor.
3. Removes a 24-pixel border so registration fill pixels cannot affect the
   measurements.
4. Fits one robust scalar exposure gain in linear-luminance midtones for each
   combiner relative to the ARW anchor. This removes global brightness bias but
   does not normalize local tone response.
5. Measures 9 x 9 low-pass luminance RMSE in anchor-defined shadows
   (percentiles 0.2-12), midtones (20-80), and highlights (88-99.8).
6. Measures high-pass correlation separately, so acuity and texture do not get
   mistaken for tonal latitude.
7. Checks low and high clipping within the valid crop interior.

The median fitted exposure correction was -0.10 EV for PixelShift2DNG and
+0.00 EV for Sony ARQ. The public panels use these same fitted gains and lock
the display transform to the ARW anchor.

## Result

| Diagnostic | PixelShift2DNG wins | Sony ARQ wins | Reading |
| --- | ---: | ---: | --- |
| Shadow low-pass error | 0/5 | 5/5 | Sony was consistently closer to the ARW tonal anchor. |
| Highlight low-pass error | 1/5 | 4/5 | Sony was usually closer in the highlight tail. |
| Midtone low-pass error | 3/5 | 2/5 | Mixed; no broad winner. |
| High-pass detail correlation | 5/5 | 0/5 | PixelShift2DNG retained the closer fine-structure relationship. |

Neither combiner clipped valid pixels in the five evaluated crop interiors.

For the narrow question asked here, Sony ARQ is therefore the stronger
latitude reference. PixelShift2DNG remains the stronger detail reference in
these crops. Calling either one the universal winner would combine two
different properties and overstate this small audit.

## Effect on the main report

The existing PS16/JXL results remain valid as measurements of codec loss from
their declared PixelShift2DNG reference. Where matching Sony ARQ data exists,
the report now adds one bounded combiner audit with a shared view dropdown for
normal, highlight-separation, and shadow-recovery panels. It does not duplicate
every JPEG XL candidate or double the main result matrix.

The machine-readable measurements are in
[`metadata/pixelshift_combiner_audit.json`](../metadata/pixelshift_combiner_audit.json).
The generator is
[`scripts/run_pixelshift_combiner_audit.py`](../scripts/run_pixelshift_combiner_audit.py).
