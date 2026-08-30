# Manual Crop Selection

Review panels can use several personally selected areas without hand-writing
coordinates.

## Recommended: browser marker

Start the local marker page:

```powershell
python scripts\serve_crop_selection.py
```

Open `http://127.0.0.1:8765/`. The page lists every generated guide. Left-click
inside an image to add a crop, right-click a yellow crop box to remove it, and
use Previous/Next or the sidebar to move between images. `Save crop plan`
writes `results/break_even_crop_guides/crop_plan.json` directly. The crop size
defaults to 768 original-image pixels and can be changed in the toolbar.

The older Paint workflow remains available below.

## Paint workflow: 1. Create guides

```powershell
python scripts\make_crop_selection_guides.py
```

Open the generated `results/break_even_crop_guides/**/ps16_guide.png` in Paint.
Use a solid pure-magenta marker (`#FF00FF`) at least 5x5 pixels large in each
interesting area. One guide may contain any number of markers. Do not use a
brush with anti-aliasing or transparency: the parser looks for exact RGB
`255,0,255` pixels.

## Paint workflow: 2. Read the guides

```powershell
python scripts\read_crop_selection_guides.py
```

The result is `results/break_even_crop_guides/crop_plan.json`. Each marker is
converted from thumbnail coordinates to the original PS16 coordinates and
centered into a square crop.

## Paint workflow: 3. Generate panels from the plan

```powershell
python scripts\make_break_even_review_panels.py `
  --crop-plan results\break_even_crop_guides\crop_plan.json
```

The plan is deliberately separate from the image-analysis code: a marker is a
human review choice, not a claim that the area is statistically representative.
It is especially useful for selecting the lp/mm area on the Adox/Vlad target,
film grain, text, edges, and difficult shadow/highlight regions.
