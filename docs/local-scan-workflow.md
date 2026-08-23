# Local Scan Workflow

This is the private/local workflow for adding real camera-scanned film material
without committing private scans or generated results to Git.

It does not run the public FADGI/OpenDICE test data under `testdata/`. Those
files belong to the reproducible public latitude-stress track:

```powershell
python scripts\run_public_latitude_v2.py --publish-figures
```

## Folder Layout

Put each scan set under:

```text
input/<scan-set-name>/
```

The `input/` folder is ignored by Git. Keep scan-set names descriptive enough to
identify the film stock and year locally, for example:

```text
input/Kodak Gold 200-5 1997/
input/Kodak5035 H190-1983/
```

## Intake Manifest

Create or refresh the local sidecar:

```powershell
python scripts\create_scan_manifest.py "input\<scan-set-name>" `
  --film-stock "<film stock>" `
  --film-type "color negative" `
  --shot-year "<year>" `
  --force
```

The manifest records capture groups, PixelShift sequences, ADC levels already
present, privacy status, and local archive triage. Use `--hash` only when you
need strong file identity checks; it can be slow for large scan folders.

## Adobe DNG Converter Candidates

If ADC DNG/JXL candidates are missing, generate them:

```powershell
python scripts\run_adobe_dng_jxl_batch.py "input\<scan-set-name>"
```

For break-even work, include levels that bracket the 61 MP raw file size. The
runner accepts any level named `dNNN`, where `d020` means Adobe DNG Converter
`-jxl_distance 0.20`:

```powershell
python scripts\run_adobe_dng_jxl_batch.py "input\<scan-set-name>" `
  --levels lossless d003 d005 d010 d015 d020 d030 d050
```

To avoid creating candidates for every root-level DNG, pass only the intended
source stems. This is useful when the folder contains both PixelShift 4 and
PixelShift 16 DNG masters but the current test only needs PixelShift 16. The
example stems below are anonymized:

```powershell
python scripts\run_adobe_dng_jxl_batch.py "input\<scan-set-name>" `
  --levels lossless d003 d005 d010 d015 d020 d030 d050 `
  --source "DSC0001-DSC0016" `
  --source "DSC0020-DSC0035"
```

The output goes to:

```text
input/<scan-set-name>/adc_jxl_dng/<level>/
```

## Run The Local Study Queue

Run all detected local scan sets:

```powershell
python scripts\run_local_scan_study.py
```

The runner:

- discovers scan folders under `input/`
- skips review folders whose names start with `_`
- checks which root DNGs have all selected ADC levels
- skips already complete verification results unless `--force` is passed
- runs `scripts/run_dng_jxl_verification.py`
- writes a local index under `results/local_scan_study/`

Dry-run before a heavy run:

```powershell
python scripts\run_local_scan_study.py --dry-run
```

Run one scan set only:

```powershell
python scripts\run_local_scan_study.py --scan-root "input\<scan-set-name>"
```

Analyze the same expanded break-even levels:

```powershell
python scripts\run_local_scan_study.py `
  --scan-root "input\<scan-set-name>" `
  --level lossless --level d003 --level d005 --level d010 `
  --level d015 --level d020 --level d030 --level d050
```

## Outputs

Per scan set:

```text
results/dng_jxl_verification/<scan-set-slug>_colorpatch/
```

The DNG/JXL verifier writes pixel metrics, patch-color metrics, and
metadata/ICC diff outputs for each source/candidate pair:

```text
metadata_diff.csv
metadata_diff.json
metadata_diff_summary.csv
```

Local cross-scan index:

```text
results/local_scan_study/LOCAL_SCAN_STUDY_INDEX.md
results/local_scan_study/local_scan_study_index.json
```

Storage-budget size index:

```powershell
python scripts\run_storage_budget_index.py
```

The output goes to:

```text
results/storage_budget_index/STORAGE_BUDGET_INDEX.md
results/storage_budget_index/storage_budget_index.csv
results/storage_budget_index/storage_budget_index.json
```

This index is deliberately narrow. It only compares retained-master file sizes
for paired single-shot raw, PixelShift 4 DNG, PixelShift 16 DNG, and ADC JXL DNG
candidates. It does not measure image quality, registration, resolved detail, or
color accuracy.

Archival break-even matrix:

```powershell
python scripts\run_archival_break_even.py --write-templates
```

This writes:

```text
results/archival_break_even/ARCHIVAL_BREAK_EVEN_MATRIX.md
results/archival_break_even/archival_break_even_matrix.csv
results/archival_break_even/archival_break_even_matrix.json
results/archival_break_even/raw61_loss_template.csv
results/archival_break_even/structure_metrics_template.csv
```

The break-even matrix joins the local manifest, storage budget, DNG/JXL
verification summaries, metadata diff summaries, and optional external
RAW61/structure metrics. If those external metrics are missing, verdicts stay
blocked. This is intentional: JPEG XL-vs-PS16 metrics alone cannot answer
whether PS16 JXL beats 61 MP raw as an archive master.

When renderer/registration or target/SFR measurements are available, pass them
back in:

```powershell
python scripts\run_archival_break_even.py `
  --level lossless --level d003 --level d005 --level d010 `
  --level d015 --level d020 --level d030 --level d050 `
  --raw-loss-csv results\archival_break_even\raw61_loss.csv `
  --structure-csv results\archival_break_even\structure_metrics.csv
```

These outputs are ignored by Git because they may reference private scan
folders and are reproducible from local inputs.

## What To Add Next

For each future film stock or representative frame, try to include:

- a normal 61 MP single-shot raw capture
- PixelShift 4 where practical
- PixelShift 16 where practical
- the PixelShift2DNG outputs used in the real archive workflow
- ADC DNG/JXL candidates at `lossless`, `d003`, `d005`, and `d010`

The current runner can already process the JXL/DNG verification layer. The next
major method layer is a fully color-managed renderer/export comparison that
produces the RAW61-vs-PS16 and structure/target CSVs consumed by
`scripts/run_archival_break_even.py`.
