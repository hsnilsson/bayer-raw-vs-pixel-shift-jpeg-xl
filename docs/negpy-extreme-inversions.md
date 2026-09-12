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
