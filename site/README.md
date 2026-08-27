# Report Site

This folder is the publishable static site artifact for the JPEG XL vs
PixelShift DNG investigation.

Recommended local publication build:

```powershell
python scripts\generate_break_even_report_site.py `
  --output site\index.html `
  --copy-panels-to site\assets\review-panels
```

Do not commit locally generated scan panels automatically. Copy only selected
owner-approved or public-data panels into `site/assets/` before building a
public release.
