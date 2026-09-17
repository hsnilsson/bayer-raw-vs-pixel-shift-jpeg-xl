param(
    [string]$ScratchRoot,
    [ValidateSet('Setup','Check','Test','Report','FreshRendered','Auxiliary','Controlled','Full','VerifyArchive','Locate')][string]$Stage='Check',
    [string]$OriginalPath
)
$ErrorActionPreference='Stop'
$archiveRoot = Join-Path $PSScriptRoot 'archive/study-20260917'
$python = Join-Path $archiveRoot 'tooling/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Archive missing. See STUDY-WORKSPACE.md for placement and restoration.' }
if ($Stage -eq 'VerifyArchive') {
    & $python -I -S -B (Join-Path $archiveRoot 'archive.py') verify
    if ($LASTEXITCODE -ne 0) { throw 'Archive verification failed' }
    return
}
if ($Stage -eq 'Locate') {
    if (-not $OriginalPath) { throw 'Locate requires -OriginalPath' }
    & $python -I -S -B (Join-Path $archiveRoot 'archive.py') locate $OriginalPath
    if ($LASTEXITCODE -ne 0) { throw 'Original path was not found in archive' }
    return
}
$setupArgs = @('setup')
if ($ScratchRoot) { $setupArgs += @('--scratch',$ScratchRoot) }
& $python -I -S -B (Join-Path $PSScriptRoot 'scripts/study_workspace.py') @setupArgs
if ($LASTEXITCODE -ne 0) { throw 'Study workspace setup failed' }
if ($Stage -eq 'Setup') { return }
$Work = Join-Path $PSScriptRoot 'work/study'
$config = Get-Content -Raw -LiteralPath (Join-Path $Work 'restore.json') | ConvertFrom-Json
$p = $config.paths
$launcher = Join-Path $PSScriptRoot 'scripts/study_runtime.py'
function Invoke-Study([string]$Mode,[string]$Script,[string[]]$Arguments=@()) {
    & $p.python -I -S -B $launcher $Mode $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Study stage failed: $Script ($LASTEXITCODE)" }
}
if ($Stage -eq 'Test') {
    Invoke-Study rendered '--tests'
    return
}
if ($Stage -eq 'Check') {
    & $p.python -I -S -B (Join-Path $PSScriptRoot 'scripts/study_workspace.py') check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed' }
    Invoke-Study rendered '--runtime-check'
    Invoke-Study controlled '--runtime-check'
    Invoke-Study muimg '--runtime-check'
    Invoke-Study rendered 'scripts/check_verified_release.py'
    Invoke-Study rendered 'scripts/check_report_site.py'
    return
}
if ($Stage -in @('FreshRendered','Full')) {
    # New results directory guarantees that no completed measurement row is reused.
    $freshResults = Join-Path $p.report 'results/fresh-measurements'
    if (Test-Path -LiteralPath $freshResults) { throw 'Fresh results already exist. Restore into a new working directory to start another cold run.' }
    Invoke-Study rendered 'scripts/create_verified_inventory.py' @('--archive',$p.archive_checkout,'--rgb16-root',$p.rgb16_root,'--f45-root',$p.f45_root,'--results',$freshResults)
    Invoke-Study rendered 'scripts/run_responsive.py' @('scripts/run_verified_rebuild.py','--archive',$p.archive_checkout,'--f45-root',$p.f45_root,'--tools',$p.tools,'--exiftool',$p.exiftool,'--scratch',$p.scratch,'--results',$freshResults,'--lossless-pilot')
    Invoke-Study rendered 'scripts/run_responsive.py' @('scripts/refine_native_registration.py','--results',$freshResults)
    Invoke-Study rendered 'scripts/build_verified_contexts.py' @('--results',$freshResults)
    Invoke-Study rendered 'scripts/audit_render_lineage.py' @('--results',$freshResults,'--exiftool',$p.exiftool)
    Invoke-Study rendered 'scripts/run_responsive.py' @('scripts/build_verified_overviews.py','--results',$freshResults,'--djxl',(Join-Path $p.tools 'djxl.exe'),'--scratch',(Join-Path $p.scratch 'overviews'))
    Invoke-Study rendered 'scripts/finalize_verified_viewers.py' @('--results',$freshResults)
    Invoke-Study rendered 'scripts/check_verified_cache.py' @('--results',$freshResults)
    if ($Stage -eq 'FreshRendered') { return }
}
if ($Stage -in @('Controlled','Full')) {
    Invoke-Study controlled 'scripts/run_controlled_exposure_latitude.py' @('--source-root',$p.controlled_sources,'--exiftool',$p.exiftool,'--output-dir',(Join-Path $Work 'controlled-results'),'--public-json',(Join-Path $Work 'controlled-results/public.json'),'--figure-dir',(Join-Path $Work 'controlled-results/figures'))
    & $p.python -I -S -B (Join-Path $p.archive 'compare_controlled.py') (Join-Path $p.report 'metadata/controlled_exposure_latitude.json') (Join-Path $Work 'controlled-results/metrics.json') (Join-Path $Work 'controlled-results/comparison.json')
    if ($LASTEXITCODE -ne 0) { throw 'Fresh controlled-exposure values differ from the frozen table' }
    if ($Stage -eq 'Controlled') { return }
}
if ($Stage -in @('Auxiliary','Full')) {
    Invoke-Study rendered 'scripts/audit_dng_evidence.py' @('--archive',$p.archive_checkout,'--lossy',(Join-Path $Work 'qualifications/lossy.json'),'--lossless',(Join-Path $Work 'qualifications/lossless.json'),'--crop-plan',$p.crop_plan,'--djxl',(Join-Path $p.tools 'djxl.exe'),'--scratch',(Join-Path $p.scratch 'dng'))
    Invoke-Study rendered 'scripts/audit_controlled_evidence.py' @('--source-root',$p.controlled_sources,'--exiftool',$p.exiftool)
    Invoke-Study public-exact 'scripts/rebuild_public_evidence.py' @('--inputs',$p.report,'--tools',$p.tools,'--scratch',(Join-Path $p.scratch 'public'))
    Invoke-Study rendered 'scripts/rebuild_combiner_evidence.py' @('--archive',$p.archive_checkout,'--rawtherapee',$p.rawtherapee,'--scratch',(Join-Path $p.scratch 'combiner'))
    if ($Stage -eq 'Auxiliary') { return }
}
if ($Stage -in @('Report','Full')) {
    $releaseArguments = @()
    if ($Stage -eq 'Full') { $releaseArguments = @('--results',$freshResults) }
    Invoke-Study rendered 'scripts/build_verified_release.py' $releaseArguments
    Invoke-Study rendered 'scripts/generate_break_even_report_site.py'
    Invoke-Study rendered 'scripts/check_verified_release.py'
    Invoke-Study rendered 'scripts/check_report_site.py'
}
