# Test Data

This directory is for public or redistributable test images used by the JPEG XL
vs DNG/PixelShift investigation.

The repository license does not relicense downloaded test files. Keep source
sidecars and verify the rights for each source before redistributing the data or
derived figures.

Run:

```powershell
python scripts\download_testdata.py
```

That downloads deterministic FADGI/OpenDICE target files and reference values.

To also resolve a few public-domain Library of Congress images through the LOC
API:

```powershell
python scripts\download_testdata.py --include-loc --loc-count 3
```

After every download the script writes:

- `downloaded_manifest.json` with file sizes and SHA-256 hashes
- one `.source.json` sidecar next to each downloaded file

The FADGI/OpenDICE files are useful for standardized target tests. The LOC
images are useful as ordinary photographic stress material, but they do not
replace newly photographed negatives or physical targets for PixelShift vs
single-shot capture testing.

## GitHub Size Note

Regular GitHub repositories warn on files over 50 MiB and block files over
100 MiB. Large test images should therefore use Git LFS or GitHub releases if
they exceed that limit.
