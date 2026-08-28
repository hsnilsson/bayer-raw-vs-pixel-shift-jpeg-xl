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
  --copy-panels-to site\assets\review-panels `
  --copy-contexts-to site\assets\review-contexts
```

Do not commit locally generated scan panels or full-size renders automatically.
Copy only selected owner-approved or public-data review artifacts into
`site/assets/` before building a public release.
