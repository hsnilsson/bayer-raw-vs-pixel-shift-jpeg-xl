# Publication Checklist

Before publishing or pushing a release branch:

- Run `python scripts\check_publication_ready.py`.
- Run `python scripts\audit_publication_safety.py --include-ignored` if you want
  to inspect private/generated local folders before sharing screenshots or zips.
- Confirm `LICENSE` and `THIRD_PARTY_DATA.md` are present and accurate.
- Confirm third-party data rights are documented before publishing any bundled
  images or derived figures.
- Confirm no private DNG, ARW, TIFF, XMP, or FilmLab exports are staged.
- Confirm no identifiable people are present in public sample images unless
  intentionally licensed and documented.
- Confirm all public test data has source sidecars or a manifest entry.
- Confirm all downloaded public files have SHA-256 hashes.
- Confirm no camera serial numbers, owner names, GPS data, or local absolute
  paths are present in tracked metadata.
- Confirm large files over 100 MiB are not committed to regular Git unless using
  a deliberate Git LFS/release strategy.
- If committing public test images, confirm `git lfs version` works and
  `.gitattributes` marks the image paths as LFS.
- Current non-blocking `audit_publication_safety.py` warnings are expected for
  large public TIFF test images in `testdata/`. They are acceptable only because
  the files are documented public sources and the relevant paths are covered by
  Git LFS.
- Confirm private exploratory results are labelled as private/non-reproducible or
  replaced by public data.
- If publishing generated panels, copy only selected public-data panels from
  `results/` into a documented public location such as `docs/figures/`.
- Confirm `results/public_latitude_stress_v2/tool_versions.json` exists for the
  latest public run, even though `results/` itself is ignored.
- Review [NEXT_STEPS.md](../NEXT_STEPS.md) and make sure any known blockers are
  either handled or intentionally left for later.
- Review [docs/publication-summary.md](publication-summary.md) before sharing so
  the public framing matches the current evidence.

## Safe To Publish By Default

- Source code in `src/`
- Scripts in `scripts/`
- Documentation
- Public test manifests
- Small public sample derivatives with documented rights

## Not Safe By Default

- `input/`
- `outputs/`
- `work/`
- original personal scans
- camera RAW files
- PixelShift2DNG files made from private images
- FilmLab exports from private images
