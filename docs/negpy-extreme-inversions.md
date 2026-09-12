# NegPy Extreme Inversions

The review viewer includes a `NegPy extreme inversion` mode in addition to the
existing synthetic negative-density transforms. It runs the real NegPy print
pipeline on the same 768-pixel crop from each PS16, RAW61, and decoded JPEG XL
source. Each source is read at its native precision; an 8-bit crop is expanded
exactly to a 16-bit working container before NegPy (`v * 257`).

The transform uses the B&W process for the Adox target and C-41 for the color
negative sets. Each crop is metered from its PS16 reference. Those normalization
bounds are then locked for RAW61 and every JPEG XL candidate so codec differences
cannot change the transform itself. The fixed stress settings are ISO-R 50,
Print Density 1.0, Luma Range Clip 1%, Color Clip 5%, Toe -1, Shoulder -1,
with Auto Density, Auto Grade, and Cast Removal disabled. Output is 16-bit sRGB
PNG. This is an extreme edit-resilience diagnostic, not a recommended grade.

RAW61 also receives the same saved per-crop `local_raw61_alignment` translation
as the existing viewer modes before it enters NegPy.

## Deep-shadow and bright-highlight tails

The generator also adds two post-inversion tail diagnostics to the viewer:
`NegPy deepest-shadow tail` and `NegPy brightest-highlight tail`. They are a
controlled version of dragging a curve almost completely into one corner. The
darkest or brightest 1% of the PS16 reference's NegPy output is isolated on
black. Bounds come from linear-light luminance at the 0.05/1 and 99/99.95
percentiles and are then held fixed for RAW61 and every JXL layer. If the 1%
threshold lands on a quantized plateau, the whole tied plateau is included and
its actual occupancy is recorded. Brightness shows how far a pixel lies inside
the selected tail; hue shows amplified linear-RGB chromaticity. Exact neutral
black is marked white.

These views answer a narrow question: **where do the compared post-inversion
images place spatially coherent color or structure in their extreme output
tails?** They do not measure capture latitude. A larger number of marked pixels
can also come from a tone or color offset, clipping, noise, demosaicing,
resampling, or imperfect registration. Judge coherent detail that appears in
the same scene location, not pixel count alone. The metadata records the shared
bounds, per-layer tail occupancy, exact black/white occupancy, and output hashes
so the comparison can be audited.

Run the generator after the normal review viewers have been generated:

```powershell
wsl -d NegPy-Ubuntu -u negpy -- bash -lc '\
  /opt/negpy-tools/bin/uv run --no-sync \
  --directory /home/negpy/pr-update-0909 \
  python /mnt/c/a/GitHub/jpegxl-vs-dngpixelshift/scripts/make_negpy_extreme_inversions.py \
  --negpy-root /mnt/c/a/GitHub/hsnilsson/NegPy \
  --expected-negpy-revision 32ac4a2e882db5c2d2c12c1435ab4db77675f3c0 \
  --force'
```

The generator refuses a dirty NegPy worktree or a revision mismatch. It maps
the large uncompressed TIFF sources instead of loading them into memory. JPEG XL
is decoded one file at a time to a temporary PPM, which is also mapped; only each
small crop enters NegPy. The existing images and transform modes are not
overwritten. Generation details and hashes are recorded in every viewer's
`metadata.json`.

Once the NegPy crop renderings are present, create the dropdown-aware
360-pixel context previews from the completed crop pairs:

```powershell
python scripts\make_mode_specific_overviews.py `
  --viewers site\assets\review-viewers
```

The NegPy preview is calibrated from the real NegPy result for the same layer.
It is stored as a compact 8-bit navigation image; the 16-bit 768-pixel crop
remains the source for visual inspection.
