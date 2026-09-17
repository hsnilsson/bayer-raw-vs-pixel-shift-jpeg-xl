# Reproducing the corrected report

The [published report](https://hsnilsson.github.io/bayer-raw-vs-pixel-shift-jpeg-xl/) was first approved by the owner and published on 2026-09-17. Its numerical evidence is in `site/data/release.json` and `site/data/measurements.csv`. The public package includes the measured crops and the six public codec fixtures; full private scans and encoded captures remain with the owner.

## Get this report's source version

The [source repository](https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl) contains the code, report data and reproduction instructions. The fixed tag [report-2026-09-17-docs](https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl/tree/report-2026-09-17-docs) selects this documentation edition and its complete report snapshot. Cloning that tag checks out its exact commit; `git rev-parse HEAD` prints the full commit identifier.

Run these commands in PowerShell with Git installed. The report scripts below use Python 3.12 on Windows. Git LFS supports the fixture acquisition option described later.

```powershell
git clone --branch report-2026-09-17-docs --single-branch https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl.git report-reproduction
Set-Location report-reproduction
git rev-parse HEAD
```

For an existing clean checkout, select the same snapshot with:

```powershell
git fetch origin tag report-2026-09-17-docs
git switch --detach report-2026-09-17-docs
```

## Validate a public checkout

Install the [pinned numerical/image dependencies](https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl/blob/report-2026-09-17-docs/requirements-report.txt) into an isolated environment. Use a Python 3.12 installation for the first command. All subsequent Python commands name that environment's executable explicitly, so they work without an activation step. JPEG XL experiments also need the separate libjxl **0.11.2** CLI: `cjxl.exe`, `djxl.exe` and `jxlinfo.exe`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-report.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check_verified_release.py
.\.venv\Scripts\python.exe scripts/check_report_site.py
```

The last two checks use the standard library and verify the committed release and its public assets. Exact bytes, including line endings, are preserved for hash-bound files by `.gitattributes`. The Linux Pages workflow runs the same release check before deployment. Run subsequent command blocks from this checkout's root, using the same `.venv`.

## Reproduce the public codec experiment

Pull the public fixtures with Git LFS, or use the downloader and its source sidecars:

```powershell
git lfs pull
```

Or use the downloader:

```powershell
.\.venv\Scripts\python.exe scripts/download_testdata.py --include-loc --loc-count 3
```

Use either acquisition method for missing fixtures. Existing sources with matching sidecars can be reused. [Data origins and rights](https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl/blob/report-2026-09-17-docs/THIRD_PARTY_DATA.md) and [test-data acquisition details](https://github.com/hsnilsson/bayer-raw-vs-pixel-shift-jpeg-xl/blob/report-2026-09-17-docs/TESTDATA.md) are part of the same source snapshot. The six selected paths are declared by `PUBLIC_V2_INPUTS` in `scripts/run_public_latitude_v2.py`.

Replace each quoted `<...>` placeholder below with your actual local directory or file. Keep the quotes around paths containing spaces. Use a persistent scratch directory. The public experiment writes its output under `results/public-reproduction` for comparison with the committed evidence.

```powershell
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
.\.venv\Scripts\python.exe scripts/rebuild_public_evidence.py --inputs . --tools '<libjxl-0.11.2-bin>' --scratch '<persistent-scratch>/public' --site results/public-reproduction
.\.venv\Scripts\python.exe scripts/compare_public_evidence.py site/data/public-evidence.json results/public-reproduction/data/public-evidence.json
```

This runs six 2048-pixel center crops at lossless, 0.03, 0.05 and 0.10, records each source hash and original bit depth, and writes new evidence plus small comparison panels. It needs no private capture inventory or RAW files. Its evidence can be compared with `site/data/public-evidence.json`. Runtime-generated ICC header timestamps can change file hashes without changing the color transform; compare source hashes, versions, pixel checks and numerical measurements rather than requiring an identical evidence ID across runs.

## Reproduce the private rendered comparison

Owner access is required to the declared RAW/DNG originals, retained neutral TIFFs, RGB16 reference PPMs and existing encoded matrix. `metadata/verified_experiment.json` fixes the sixteen frames, twenty-two crops and ten distances. The f/4.5 retained root contains `rawtherapee_renders_f45` and `rendered_ps16_jxl_matrix_f45`. Normal renders are under the archive's `outputs/rawtherapee_renders`; its `input` tree contains scan manifests.

```powershell
.\.venv\Scripts\python.exe scripts/create_verified_inventory.py --archive '<archive-checkout>' --rgb16-root '<retained-rgb16-matrix>' --f45-root '<retained-f45-root>'
.\.venv\Scripts\python.exe scripts/run_responsive.py scripts/run_verified_rebuild.py --archive '<archive-checkout>' --f45-root '<retained-f45-root>' --tools '<libjxl-0.11.2-bin>' --exiftool '<ExifTool.exe>' --scratch '<persistent-scratch>' --lossless-pilot
```

The ignored `results/verified_report/private_inventory.json` contains local paths; it is never published. The inventory creator refuses to overwrite an existing inventory. The rebuild verifies source content and precision, checks real-image lossless round trips, repairs photographic metadata independently of image encoding, decodes each candidate once and shares that decode across all approved scopes. A completed candidate has an atomic checkpoint; a completed frame has a receipt. Resume with the same inputs and flags. An unchanged frame reuses content-verified metrics and pixels; source audit and small lossless controls still run. Metric changes do not automatically require re-encoding a valid retained JXL.

Use the responsive launcher shown above: it checks that the 64-bit Windows process priority was actually set before loading the stage. The responsive policy permits one heavy job, four codec threads and one numerical thread, with below-normal priority, an 8 GiB available-memory reserve and a 20 GiB scratch-space floor. Use persistent scratch, not existing Windows Temp files. Never run the following heavy auxiliary stages concurrently with the full RGB batch.

The rebuild entry point composes the unchanged measurement engine with a stable preview writer. It retains an existing PNG only when its pixels and all profile/metadata bytes match, apart from the ICC creation timestamp. A changing timestamp therefore cannot invalidate already completed candidates after a partial interruption. Changed pixels or color profiles still force replacement. The two-level interrupted-run regression checks this behavior explicitly.

## Auxiliary evidence and release assembly

The DNG audit requires the retained lossy and lossless qualification records, their original candidates, and the historical crop-plan JSON. It rehashes candidates before reusing full-decode/Adobe acceptance records and freshly decodes selected camera tiles:

```powershell
.\.venv\Scripts\python.exe scripts/audit_dng_evidence.py --archive '<archive-checkout>' --lossy '<lossy-qualification.json>' --lossless '<lossless-qualification.json>' --crop-plan '<historical-crop-plan.json>' --djxl '<djxl.exe>' --scratch '<persistent-scratch>/dng'
.\.venv\Scripts\python.exe scripts/audit_controlled_evidence.py --source-root '<controlled-bracket-source-root>' --exiftool '<ExifTool.exe>'
.\.venv\Scripts\python.exe scripts/rebuild_public_evidence.py --inputs '<public-checkout>' --tools '<libjxl-0.11.2-bin>' --scratch '<persistent-scratch>/public'
.\.venv\Scripts\python.exe scripts/rebuild_combiner_evidence.py --archive '<archive-checkout>' --scratch '<persistent-scratch>/combiner'
.\.venv\Scripts\python.exe scripts/build_verified_contexts.py
.\.venv\Scripts\python.exe scripts/audit_render_lineage.py --exiftool '<ExifTool.exe>'
.\.venv\Scripts\python.exe scripts/finalize_verified_viewers.py
.\.venv\Scripts\python.exe scripts/check_verified_cache.py
.\.venv\Scripts\python.exe scripts/build_verified_release.py --verify-private
.\.venv\Scripts\python.exe scripts/generate_break_even_report_site.py
.\.venv\Scripts\python.exe scripts/check_verified_release.py
.\.venv\Scripts\python.exe scripts/check_report_site.py
.\.venv\Scripts\python.exe scripts/prune_superseded_site_assets.py
.\.venv\Scripts\python.exe scripts/prune_superseded_site_assets.py --apply
.\.venv\Scripts\python.exe scripts/check_report_site.py
```

The combiner stage uses RawTherapee 5.12 and the committed neutral preset to render two source-ARW anchors; inspect its `--help` for the executable override. Its fixed selections are in `metadata/combiner_crop_plan.json`. The controlled experiment retains sensor-domain measurements and audits source identity, exposure and aggregates; it does not rerun the full bracket analysis.

Finalization removes legacy viewer metadata and writes lossless gzip byte-plane payloads with both transport and decoded-pixel hashes. Original uncompressed crop buffers move to the ignored `results/verified_report/viewer-pixels` cache, and checkpoint references are updated. A recovery journal makes interrupted exports resumable. This cache is part of subsequent unchanged-run verification and should be retained with the local results.

Release assembly rejects incomplete or mixed frame/level results, stale code, incorrect metadata and mismatched assets. The renderer reads that complete release; current tables must not be edited by hand. Legacy rendering requires an explicit `--legacy-unverified` flag and cannot target the current `site` directory. The publication workflow refuses stale HTML, CSV/JSON mismatches, wrong cohorts or exact-byte budgets, changed profiles/pixels and private absolute paths.

## Review limits

The report distinguishes native and reduced measurements and describes the retained rendering workflow and its historical provenance. DNG errors are measured in camera codes; combiner results describe agreement with their source-ARW anchor. The viewer uses RGB16 inputs and an 8-bit sRGB canvas, with RAW resampling quantization reported separately. Visual checks in the repair were machine-assisted. The report's remaining research questions describe the next steps toward a broader quality assessment.

Serve the repository with `.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1` and open `http://127.0.0.1:8765/site/index.html`. The viewer uses HTTP fetch and gzip DecompressionStream support. The [review record](https://hsnilsson.github.io/bayer-raw-vs-pixel-shift-jpeg-xl/data/review-notes.md) documents the completed checks and initial publication.
