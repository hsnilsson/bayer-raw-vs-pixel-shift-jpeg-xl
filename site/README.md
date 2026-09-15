# Report Site

This folder is the publishable static site artifact for the Bayer Raw vs
Pixel-Shift JPEG XL investigation.

Recommended local publication build:

```powershell
python scripts\make_break_even_context_images.py `
  --case "<scan-set>|<frame-id>" `
  --crop <x,y,width,height> `
  --crop-name <crop-name>

python scripts\generate_break_even_report_site.py `
  --output site\index.html `
  --copy-contexts-to site\assets\review-contexts `
  --copy-public-figures-to site\assets\public-latitude-v2 `
  --viewers site\assets\review-viewers
```

Interactive crop viewers are generated separately for selected, owner-approved
cases:

```powershell
python scripts\make_break_even_review_viewers.py `
  --output-dir site\assets\review-viewers `
  --all-complete `
  --level d020 `
  --level d022 `
  --level d025 `
  --level d028 `
  --level d030 `
  --level d200
```

To add the real NegPy-based extreme inversion to those same crops, follow
[`docs/negpy-extreme-inversions.md`](../docs/negpy-extreme-inversions.md). Run
that generator after the normal review-viewer command and before rebuilding the
report site.

After all crop modes exist, generate the compact dropdown-aware context
previews:

```powershell
python scripts\make_mode_specific_overviews.py `
  --viewers site\assets\review-viewers
```

These 8-bit previews use a per-image tone mapping fitted from each rendered
identity/transformed crop pair. They are navigation aids only; inspection and
measurement continue to use the full crop renderings.

The viewer supports side-by-side viewing, a candidate-on-reference overlay
toggle, zoom, and pan. It always includes the PS16 reference as the lossless
baseline, and `d200` is included only as a deliberately heavy-compression visual
anchor.

`Highlight separation` and `Shadow recovery` are grayscale linear-luminance
diagnostics. Their display bounds remain locked to PS16. For RAW61 only, one
scalar exposure gain is robustly fitted from aligned midtones (PS16 reference
percentiles 20-80) before the tail is expanded. This prevents a global rendered
level mismatch from masquerading as lost latitude without hiding channel-balance
differences in the normal or inversion views. PS16 JXL candidates receive no
such adjustment because their absolute difference from PS16 is codec evidence.
Keep these small derived crops limited to approved public cases.

For a local, single-pair experiment with shared histogram and tone controls,
first produce or decode both sides as 16-bit RGB images, then run:

```powershell
python scripts\make_interactive_tone_curve_prototype.py `
  --reference <16-bit-reference.tif-or-ppm> `
  --candidate <16-bit-candidate.tif-or-ppm> `
  --crop <x,y,width,height> `
  --output-dir work\tone-curve-prototype
```

Serve the output directory over HTTP because the browser loads the two raw
16-bit RGB sidecars with `fetch()`. The generator deliberately refuses 8-bit
inputs: the shared exposure, black/white window, and draggable tone curve must
run before the browser creates an 8-bit display image. The prototype is a test
of latitude in the fixed rendered RGB chain, not a measurement of all latitude
available when developing the original raw files. Keep private high-precision
crop buffers under ignored `work/`; do not copy them into the publishable site
without a separate publication review.

The separate Pixelshift combiner audit compares PixelShift2DNG and Sony ARQ
only where both were built from the same 16 source frames. It registers both
renders and independently exposure-matches them to the first source ARW, then
keeps low-pass shadow/highlight error separate from high-pass detail
correlation. Generate its compact three-column panels and JSON before the site
build:

```powershell
python scripts\run_pixelshift_combiner_audit.py `
  --plan <local-audit-plan.json> `
  --output-assets site\assets\pixelshift-combiner-audit `
  --output-json metadata\pixelshift_combiner_audit.json
```

The local plan contains paths to unpublished full-size renders and is not part
of the public artifact. The report publishes only five approved crops with a
single Normal / Highlight separation / Shadow recovery dropdown; it does not
duplicate the main JPEG XL matrix.

Do not commit locally generated scan panels or full-size renders automatically.
Static diagnostic panels stay in `results/break_even_review_panels/` by
default because they are large regenerated artifacts. Copy only selected
owner-approved or public-data review artifacts into `site/assets/` before
building a public release.
