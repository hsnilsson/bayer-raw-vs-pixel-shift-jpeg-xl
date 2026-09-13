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
