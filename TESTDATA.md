# Test Data

Public test data should live under `testdata/` with source notes and SHA-256
hashes.

The repository license does not relicense third-party test data. See
[THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md) for rights notes.

Use:

```powershell
python scripts\download_testdata.py
```

The script downloads deterministic FADGI/OpenDICE files by default. It can also
resolve Library of Congress images:

```powershell
python scripts\download_testdata.py --include-loc --loc-count 3
```

## FADGI/OpenDICE

FADGI/OpenDICE targets are useful for standardized capture-quality testing:

- spatial response
- tonal response
- color behavior
- illumination uniformity
- channel registration

They are not a replacement for real film negatives, but they make the capture
side of the investigation more credible.

Downloaded OpenDICE files currently include 35 mm negative, 35 mm positive, and
120 negative target examples plus their reference profiles.

## Library of Congress Images

Library of Congress public-domain/no-known-restrictions images are useful for
general image-processing stress tests and public examples.

They do not test:

- PixelShift registration
- Bayer vs PixelShift sampling
- real dye clouds
- real negative inversion

Always verify the individual item page before redistribution.

The initial LOC sample set uses master TIFF files from the Carol M. Highsmith
Archive. These are large 16-bit Adobe RGB files and are intended to exercise the
JXL/tonal-stress pipeline on ordinary photographic imagery.

## Private Local Data

Private scans, DNG files, ARW files, FilmLab exports, and generated experiment
outputs should stay out of Git unless intentionally anonymized and documented.

The `.gitignore` file ignores local private/generated directories such as
`input/`, `outputs/`, and `work/`.

## Large Files

Downloaded public test images can be large. This repo marks image files under
`testdata/` for Git LFS via `.gitattributes`.

Before committing downloaded TIFF/JPEG/JXL test images, make sure Git LFS is
installed:

```powershell
git lfs version
```

For this project, the current decision is to include the large public TIFF files
through Git LFS. If Git LFS is not available in a fork or mirror, commit only the
manifest and let users run `scripts/download_testdata.py` locally.
