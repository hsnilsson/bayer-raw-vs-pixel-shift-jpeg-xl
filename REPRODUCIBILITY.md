# Reproducibility

This page describes the current public reproduction path.

The public pipeline is meant to be runnable without the private images that
started the investigation. It uses public FADGI/OpenDICE targets and selected
Library of Congress TIFF files.

## Requirements

- Python 3.10 or newer
- `cjxl` and `djxl` from libjxl
- Git LFS if committing or pulling the large public TIFF files through Git
- Python packages from `pyproject.toml`

Install the Python package and public-test dependency:

```powershell
python -m pip install -e ".[public-tests]"
```

Check JPEG XL tools:

```powershell
cjxl --version
djxl --version
```

If the tools are not on `PATH`, the scripts also look under:

```text
work/jxl-tools/bin/cjxl.exe
work/jxl-tools/bin/djxl.exe
```

## Data

If the public test images are already present through Git LFS, pull them:

```powershell
git lfs install
git lfs pull
```

Otherwise download public test data:

```powershell
python scripts\download_testdata.py --include-loc --loc-count 3
```

The download script writes `testdata/downloaded_manifest.json` and `.source.json`
sidecars with source information and SHA-256 hashes.

## Run Public Latitude Stress v2

```powershell
python scripts\run_public_latitude_v2.py --publish-figures
```

This writes:

- `results/public_latitude_stress_v2/metrics.csv`
- `results/public_latitude_stress_v2/metrics.json`
- `results/public_latitude_stress_v2/tool_versions.json`
- `results/public_latitude_stress_v2/run_manifest.json`
- `results/public_latitude_stress_v2/PANELS.md`
- selected figures under `docs/figures/public-latitude-v2/`

The `results/` directory is generated local output and is ignored by Git.

## Quick Reuse Check

If the heavy encode/decode results already exist, run a light check that only
validates their original provenance and republishes selected figures:

```powershell
python scripts\run_public_latitude_v2.py --skip-stress --skip-panels --publish-figures
```

Reuse is deliberately strict. `run_manifest.json` must match the requested
parameters, current input hashes, pipeline-code hashes, Python/package versions,
JPEG XL tool versions, and recorded artifact hashes. Reuse never rewrites the
original `tool_versions.json`. Legacy results without a manifest must be rerun
once without `--skip-stress`.

## Publication Safety Audit

Before publishing:

```powershell
python scripts\check_publication_ready.py
```

Large public TIFF files correctly marked for Git LFS are reported as
informational findings. Blocking findings or warnings should be fixed before
release. The lower-level audit can also be run directly:

```powershell
python scripts\audit_publication_safety.py
```

## Clean Clone Test

The strongest check before sharing the project is:

1. Clone the repository into a new directory.
2. Install Git LFS.
3. Install the Python package with `python -m pip install -e ".[public-tests]"`.
4. Download or pull the public test data.
5. Run `python scripts\run_public_latitude_v2.py --publish-figures`.
6. Run `python scripts\check_publication_ready.py`.

The generated metrics should be comparable to the tables in
[docs/public-latitude-v2.md](docs/public-latitude-v2.md).
