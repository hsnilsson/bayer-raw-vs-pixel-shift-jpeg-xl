# Report Site

This folder is the publishable static site artifact for the JPEG XL vs
PixelShift DNG investigation.

Recommended local publication build:

```powershell
python scripts\make_break_even_context_images.py `
  --case "<scan-set>|<frame-id>" `
  --crop <x,y,width,height> `
  --crop-name <crop-name>

python scripts\generate_break_even_report_site.py `
  --output site\index.html `
  --copy-contexts-to site\assets\review-contexts `
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
  --level d030
```

The viewer supports side-by-side viewing, a candidate-on-reference overlay
toggle, zoom, and pan.
Keep these small derived crops limited to approved public cases.

Do not commit locally generated scan panels or full-size renders automatically.
Static diagnostic panels stay in `results/break_even_review_panels/` by
default because they are large regenerated artifacts. Copy only selected
owner-approved or public-data review artifacts into `site/assets/` before
building a public release.
