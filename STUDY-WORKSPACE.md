# Working with the consolidated study

The editable Git checkout and all preserved scientific inputs belong in one folder:

```text
jpegxl-study/
  study.ps1
  scripts/ src/ tests/ metadata/ profiles/ docs/ site/ testdata/
  archive/study-20260917/     # ignored; preserved snapshot, inputs and tools
  results/                  # ignored; mutable working measurements
  work/                     # ignored; configuration, logs and scratch
```

The archive is private and excluded from Git. A Git clone alone contains the public
project, not the private images. Copy the entire private `archive/` folder into
the checkout, including `study-20260917`, `tooling-extra` and
the operational receipts. `tooling-extra` supplies Node for the viewer tests.
Do not edit preserved payloads, records or checksum manifests.
The archive README documents restoration of the original frozen study and Git
history. The working project may evolve independently of that frozen snapshot.

From this folder in PowerShell:

```powershell
.\study.ps1 -Stage Setup
.\study.ps1 -Stage Check
.\study.ps1 -Stage Test
.\study.ps1 -Stage Report
```

Setup initializes the ignored private records from the archive only when no working
records exist. It derives archive/tool paths from this folder and rebases working
records after the folder moves. Run the launcher again after relocation; no original
drive letters or old worktrees are required. Existing scientific results are not
overwritten by setup. Keep the project's internal folder structure intact.

For large computations, use a dedicated scratch folder on a disk with ample room:

```powershell
.\study.ps1 -Stage Setup -ScratchRoot 'C:\jpegxl-study-scratch'
```

That optional machine-local setting is stored in ignored `work/study/restore.json`.
To return to a completely self-contained layout, pass `-ScratchRoot 'work/scratch'`.
Filenames in the private inventory are expanded when setup runs; the persisted
scratch setting can be relative. The numerical workload retains the study's
20 GiB scratch and 8 GiB available-memory floors.

`Check` verifies static dependency access, pinned environments and the current
report. `Report` regenerates the report using retained measurement rows. It does
not recompute those measurements. Full checksum verification is a separate command:

```powershell
.\study.ps1 -Stage VerifyArchive
.\study.ps1 -Stage Locate -OriginalPath 'C:\a\GitHub\jpegxl-vs-dngpixelshift\input\adox_vlad_resolution_target\_DSC0001.ARW'
```

Future scientific reruns use the same retained tools and the editable code:

```powershell
.\study.ps1 -Stage FreshRendered  # new rendered rows and their assets
.\study.ps1 -Stage Controlled     # fresh controlled-exposure measurements
.\study.ps1 -Stage Auxiliary      # DNG/public/combiner evidence
.\study.ps1 -Stage Full           # fresh rendered + controlled + auxiliary + release
```

FreshRendered and Full require an unused `results/fresh-measurements` directory.
Preserve or relocate a previous experimental results directory deliberately before
starting a new run. Do not replace the archived evidence with new experiments.
Fresh analysis code has a new identity: the frozen Check stage rejects altered
analysis code against retained rows, while fresh runs establish their own evidence.
Timing values are new observations. Exact public codec bytes use the retained ICC
profile, including its original timestamp, as explained in the archive README.

The launcher pins separate rendered, controlled and MUIMG package environments;
the controlled pipeline needs NumPy 2.3.5. It isolates Python file access and native
command arguments to the project, archive and selected scratch directory, and
explicitly prohibits Python writes inside the nested archive. Native indirect OS
access is not an OS-level sandbox. Installed system tools are not required for the
retained measurements; the binaries in the archive require compatible Windows x64.

For routine development, commit code and intended public report changes normally.
`archive/`, `results/` and `work/` stay ignored. The history rewrite removed older
generated assets; see `docs/HISTORY-REWRITE.md` before using historical checkouts.

## Presentation-only changes

For viewer keyboard behavior, layout or report styling, commit the source changes
first, then refresh the public packaging and render it. This checks the existing
scientific code, evidence and image hashes without recomputing measurements:

```powershell
$python = './archive/study-20260917/tooling/python/python.exe'
$runtime = './scripts/study_runtime.py'
$sourceRef = git rev-parse HEAD
& $python -I -S -B $runtime rendered scripts/build_verified_release.py --refresh-public --source-ref $sourceRef
& $python -I -S -B $runtime rendered scripts/render_verified_report.py
& $python -I -S -B $runtime rendered scripts/check_verified_release.py
& $python -I -S -B $runtime rendered scripts/check_report_site.py
```

Stop if a command fails. Commit the refreshed public files after the checks pass.
The refresh changes release identifiers and their CSV labels, but retains all
measurement values and scientific image assets. Rendering HTML alone leaves the
release's report-code hashes stale and correctly fails the publication gate.
Use the consolidated checkout or a worktree of it; do not merge old-history
worktrees from the former C: repository into this repository.
