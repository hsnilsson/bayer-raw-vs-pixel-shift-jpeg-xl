# Report Site

This folder is the publishable static site artifact for the JPEG XL vs
PixelShift DNG investigation.

Recommended local publication build:

```powershell
python scripts\generate_break_even_report_site.py `
  --output site\index.html `
  --copy-panels-to site\assets\review-panels
```

Do not commit locally generated private scan panels. Replace private negatives
with publishable material before building a public release.

