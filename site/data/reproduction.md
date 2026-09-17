# Reproducing the corrected report

The current report is a local release awaiting owner review. Its complete numerical evidence is in `site/data/release.json` and `site/data/measurements.csv`. Full private scans and encoded captures are intentionally absent from the public repository.

## Validate a public checkout

Python 3.12 was used for this release. Install the pinned numerical/image dependencies into an isolated environment. JPEG XL scientific decoding uses the separate libjxl **0.11.2** CLI, including `cjxl`, `djxl` and `jxlinfo`; the imagecodecs package's internal JPEG XL version is not substituted for it.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-report.txt
.venv/Scripts/python -m pip install --no-deps -e .
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python scripts/check_verified_release.py
.venv/Scripts/python scripts/check_report_site.py
```

The last two checks use the standard library and can run without image-processing dependencies. They verify the committed release and its assets without private sources. Exact bytes, including line endings, are preserved for hash-bound files by `.gitattributes`. The Linux Pages workflow runs the same release check before deployment.

## Reproduce the public codec experiment

Pull the public fixtures with Git LFS, or use the downloader and its source sidecars:

```powershell
git lfs pull
python scripts/download_testdata.py --include-loc --loc-count 3
```

Use one acquisition method as needed; sources already present with matching sidecars need not be downloaded again. Data origins and rights are described in `THIRD_PARTY_DATA.md` and `TESTDATA.md`. The six selected paths are declared by `PUBLIC_V2_INPUTS` in `scripts/run_public_latitude_v2.py`; the old v2 measurements are not reused.

```powershell
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
python scripts/rebuild_public_evidence.py --inputs . --tools <libjxl-0.11.2-bin> --scratch <persistent-scratch>/public --site results/public-reproduction
python scripts/compare_public_evidence.py site/data/public-evidence.json results/public-reproduction/data/public-evidence.json
```

This runs six 2048-pixel center crops at lossless, 0.03, 0.05 and 0.10, records each source hash and original bit depth, and writes new evidence plus small comparison panels. It needs no private capture inventory or RAW files. Its evidence can be compared with `site/data/public-evidence.json`. Runtime-generated ICC header timestamps can change file hashes without changing the color transform; compare source hashes, versions, pixel checks and numerical measurements rather than requiring an identical evidence ID across runs.

## Reproduce the private rendered comparison

Owner access is required to the declared RAW/DNG originals, retained neutral TIFFs, RGB16 reference PPMs and existing encoded matrix. `metadata/verified_experiment.json` fixes the sixteen frames, twenty-two crops and ten distances. The f/4.5 retained root contains `rawtherapee_renders_f45` and `rendered_ps16_jxl_matrix_f45`. Normal renders are under the archive's `outputs/rawtherapee_renders`; its `input` tree contains scan manifests.

```powershell
python scripts/create_verified_inventory.py --archive <archive-checkout> --rgb16-root <retained-rgb16-matrix> --f45-root <retained-f45-root>
python scripts/run_responsive.py scripts/run_verified_rebuild.py --archive <archive-checkout> --f45-root <retained-f45-root> --tools <libjxl-0.11.2-bin> --exiftool <ExifTool.exe> --scratch <persistent-scratch> --lossless-pilot
```

The ignored `results/verified_report/private_inventory.json` contains local paths; it is never published. The inventory creator refuses to overwrite an existing inventory. The rebuild verifies source content and precision, checks real-image lossless round trips, repairs photographic metadata independently of image encoding, decodes each candidate once and shares that decode across all approved scopes. A completed candidate has an atomic checkpoint; a completed frame has a receipt. Resume with the same inputs and flags. An unchanged frame reuses content-verified metrics and pixels; source audit and small lossless controls still run. Metric changes do not automatically require re-encoding a valid retained JXL.

Use the responsive launcher shown above: it checks that the 64-bit Windows process priority was actually set before loading the stage. The responsive policy permits one heavy job, four codec threads and one numerical thread, with below-normal priority, an 8 GiB available-memory reserve and a 20 GiB scratch-space floor. Use persistent scratch, not existing Windows Temp files. Never run the following heavy auxiliary stages concurrently with the full RGB batch.

The rebuild entry point composes the unchanged measurement engine with a stable preview writer. It retains an existing PNG only when its pixels and all profile/metadata bytes match, apart from the ICC creation timestamp. A changing timestamp therefore cannot invalidate already completed candidates after a partial interruption. Changed pixels or color profiles still force replacement. The two-level interrupted-run regression checks this behavior explicitly.

## Auxiliary evidence and release assembly

The DNG audit requires the retained lossy and lossless qualification records, their original candidates, and the historical crop-plan JSON. It rehashes candidates before reusing full-decode/Adobe acceptance records and freshly decodes selected camera tiles:

```powershell
python scripts/audit_dng_evidence.py --archive <archive-checkout> --lossy <lossy-qualification.json> --lossless <lossless-qualification.json> --crop-plan <historical-crop-plan.json> --djxl <djxl.exe> --scratch <persistent-scratch>/dng
python scripts/audit_controlled_evidence.py --source-root <controlled-bracket-source-root> --exiftool <ExifTool.exe>
python scripts/rebuild_public_evidence.py --inputs <public-checkout> --tools <libjxl-0.11.2-bin> --scratch <persistent-scratch>/public
python scripts/rebuild_combiner_evidence.py --archive <archive-checkout> --scratch <persistent-scratch>/combiner
python scripts/build_verified_contexts.py
python scripts/audit_render_lineage.py --exiftool <ExifTool.exe>
python scripts/finalize_verified_viewers.py
python scripts/check_verified_cache.py
python scripts/build_verified_release.py --verify-private
python scripts/generate_break_even_report_site.py
python scripts/check_verified_release.py
python scripts/check_report_site.py
python scripts/prune_superseded_site_assets.py
python scripts/prune_superseded_site_assets.py --apply
python scripts/check_report_site.py
```

The combiner stage uses RawTherapee 5.12 and the committed neutral preset to render two source-ARW anchors; inspect its `--help` for the executable override. Its fixed selections are in `metadata/combiner_crop_plan.json`. The controlled experiment retains sensor-domain measurements and audits source identity, exposure and aggregates; it does not rerun the full bracket analysis.

Finalization removes legacy viewer metadata and writes lossless gzip byte-plane payloads with both transport and decoded-pixel hashes. Original uncompressed crop buffers move to the ignored `results/verified_report/viewer-pixels` cache, and checkpoint references are updated. A recovery journal makes interrupted exports resumable. This cache is part of subsequent unchanged-run verification and should be retained with the local results.

Release assembly rejects incomplete or mixed frame/level results, stale code, incorrect metadata and mismatched assets. The renderer reads that complete release; current tables must not be edited by hand. Legacy rendering requires an explicit `--legacy-unverified` flag and cannot target the current `site` directory. The publication workflow refuses stale HTML, CSV/JSON mismatches, wrong cohorts or exact-byte budgets, changed profiles/pixels and private absolute paths.

## Review limits

The report identifies native and reduced scopes, adopted legacy encodes, incomplete historical cryptographic lineage, and unresolved effective RAW/DNG render settings. DNG camera-code errors do not establish display-color superiority. The combiner comparison measures reference agreement, not recovered latitude. Browser inputs are RGB16 but the sRGB canvas is 8-bit; RAW resampling quantization is disclosed separately. All visual review in this repair is machine-assisted, not a blinded human study.

Serve the repository with `python -m http.server 8765 --bind 127.0.0.1` and open `http://127.0.0.1:8765/site/index.html`. The viewer requires HTTP fetch and gzip DecompressionStream support. Owner review and a separate publication instruction remain necessary before pushing the site.
