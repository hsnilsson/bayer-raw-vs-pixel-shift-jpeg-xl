# Restartable PS16 mass-scan workflow for Windows

This is the operational, safety-first workflow for continuously processing Sony
PS16 rolls while scanning. It is conservative about verification, but cleanup
is configurable: you can keep a rolling window of recent groups, move older raws
to recoverable quarantine, or delete them once they fall outside the window.

## What the first version automates

For one flat incoming roll folder, the runner:

1. polls for `.ARW` files and persists observations in SQLite;
2. waits until file size and modification time have been unchanged for the configured interval;
3. asks ExifTool for Sony `PixelShiftInfo`, requiring exactly shots 1–16 from one group;
4. drives PixelShift2DNG's **Analyze + Convert All** button through the existing Windows UI helper;
5. waits for the output DNG to stop changing and checks that ExifTool can read positive dimensions;
6. creates every enabled Adobe DNG Converter JPEG XL profile in a temporary folder;
7. verifies file count, nonzero size, dimensions, JPEG XL compression, configured distance when reported, and SHA-256 before atomically publishing each DNG;
8. creates an ASCII-only FilmLab staging batch and records film stock/profile metadata;
9. imports a matching positive export and makes a small JPEG preview; and
10. preserves restart state, errors, output hashes, and a plain-text log.

The example has one `d005` archive-master profile. The same verified archive
master is staged for FilmLab, so the pipeline does not create a separate compact
viewing DNG. Profile names are independent of distances and can be changed. The
archive choice remains a policy decision: prior tests showed that lossy ADC DNG
changes the raw image state, so keep representative quality evidence and the
physical negatives.

## Local tool inventory (2026-08-30)

The development workstation had:

- PixelShift2DNG 1.1.11.106 at `C:\Program Files\LibRaw\PixelShift2DNG\PixelShift2DNG.exe`;
- Adobe DNG Converter 18.5 at `C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe`;
- ExifTool 13.12 at `C:\Program Files\ExifTool\ExifTool.exe`; and
- RawTherapee 5.12.

FilmLab was not found in the standard Program Files or local-program locations.
Its command-line interface and stable UI controls therefore could not be verified.
The implemented boundary is reproducible ASCII staging plus an optional,
user-supplied launch command. This also avoids the already observed failure with
Swedish characters. The default FilmLab input is the verified `archive` profile,
not a second viewing copy. Because prior tests observed compatibility/color-path
concerns with ADC JXL DNG files, validate this handoff on a small representative
roll before enabling cleanup.

## One-time setup

Install Python 3.10+ and the project dependencies (Pillow is used for previews):

```powershell
python -m pip install -e .
```

Copy the example without overwriting it:

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Set a unique `batch.id` for every roll and fill in all paths. Keep:

- `incoming` as a flat folder containing only the current roll's incoming ARWs;
- `work` and `filmlab_staging` on fast local storage;
- `archive`, `positives`, and ideally `quarantine` on the intended retained volume;
- `filmlab_staging` strictly ASCII-only; and
- `cleanup.enabled` as `false` for initial sessions.

`watch.minimum_free_gib` stops new conversion work when the incoming, work, or
archive volume falls below the configured guard. Set it from measured temporary
space needs; `0` disables the guard.

Paths do not need to exist in advance except `incoming`. The runner creates its
own output folders. Do not point `work`, `archive`, or `quarantine` at the same
folder as `incoming`.

## Before a real scanning session

First print the intended actions without writing queue state or launching either converter:

```powershell
.\start.ps1 -Config .\config.json -Command once -DryRun
```

Dry-run still reads stable ARW metadata with ExifTool. A new or changed file is
never trusted from its camera timestamp: it must be observed unchanged for the
full `watch.stable_seconds` interval. A one-shot dry-run immediately after files
arrive can therefore report no ready groups; run it again after that interval.

Start the continuous queue:

```powershell
.\start.ps1 -Config .\config.json -Command watch
```

Leave that PowerShell window open while scanning. `Ctrl+C` stops after the
current safe boundary; rerun the same command to resume from `queue.sqlite3`.
Run a single polling/conversion pass with `-Command once`.

## FilmLab handoff

For each verified negative, the staging folder contains an ASCII-safe DNG and
`filmlab_batch.json` with the roll's `film_stock`, `filmlab_profile`, group ID,
and export folder. In FilmLab 3.5:

1. import the staged DNG;
2. apply the roll profile named in `filmlab_batch.json`;
3. export the positive into `positive-exports`; and
4. preserve the staged filename stem exactly (the extension may change).

The next queue pass copies and hashes the export under `paths.positives` and
creates the preview. If a local FilmLab invocation is proven, set
`filmlab.launch_command` to an argument array. `{staging_dir}` and `{input}` are
expanded, for example `["C:\\Path\\FilmLab.exe", "{input}"]`. It is launched
only once per queue workspace.

## Status and recovery

Show every group and its current state:

```powershell
.\start.ps1 -Config .\config.json -Command status
```

The durable records are:

- `work\queue.sqlite3` — per-file observations, group states, verified output hashes;
- `work\pipeline.log` — readable chronological log;
- `work\errors\<group>.json` — isolated error details; and
- `archive\<profile>\*.dng` — published, verified profile outputs.

After correcting a tool/path/input problem, explicitly retry one Sony group ID:

```powershell
.\start.ps1 -Config .\config.json -Command retry -GroupId 17163427
.\start.ps1 -Config .\config.json -Command once
```

Existing outputs are reused only when their current size and SHA-256 still match
the queue record. ADC work happens below `work\adc-temp`; an interrupted temp
file is never treated as an archive result.

## Retention cleanup

Keep `cleanup.enabled=false` until the workflow is proven on your own storage
layout. By default, a FilmLab positive is also required before a group can be
approved for cleanup.

First approve each reviewed group:

```powershell
.\start.ps1 -Config .\config.json -Command approve -GroupId 17163427
```

Approval rechecks every required retained output against its saved size and
SHA-256, then computes and stores SHA-256 for all 16 ARWs. This intentionally
takes time but happens outside the capture-critical conversion loop.

Then set `cleanup.enabled=true` and run the retention sweep. The approval token
must exactly equal `batch.id`:

```powershell
.\start.ps1 -Config .\config.json `
  -Command prune -ApprovalToken roll-2026-001
```

By default the pipeline keeps the newest two approved groups and prunes older
ones. Set `cleanup.retention_groups` to match your disk budget. With
`cleanup.prune_mode="move"` the older camera raws go to recoverable quarantine;
with `cleanup.prune_mode="delete"` they are removed after the verification
checks have already passed.

The source DNG, archive-master DNG, positives, previews, queue, and checksums
remain. If Windows or the runner stops midway through a move-based prune, run
the same command again. It verifies that each raw exists in exactly one of the
expected places and resumes the remaining work; conflicting duplicates or
checksum changes stop the operation.

## Known limits

- PixelShift2DNG is a GUI application. The helper can reuse its existing window,
  but the incoming roll folder must stay fixed and flat for the session.
- FilmLab processing remains manual until a stable, testable CLI or UI contract
  is available. Do not automate clicks based only on screen coordinates.
- ExifTool readability and tags are strong smoke checks, not an independent full
  DNG decoder or a visual quality verdict.
- The first version is single-process. A process lock refuses a second watcher
  against the same `work` database and is released automatically after a crash.
- A 1 TB disk still needs free-space monitoring and an external backup policy;
  retention cleanup is not a backup.

## Synthetic verification

The test suite creates 16 tiny fake ARWs and fake converter outputs in a temporary
folder. It exercises restart/idempotency, the archive-master profile, FilmLab staging,
positive preview creation, explicit approval, a rejected token, and recoverable
retention cleanup without touching real photographs:

```powershell
python -m unittest discover -s tests -v
```
