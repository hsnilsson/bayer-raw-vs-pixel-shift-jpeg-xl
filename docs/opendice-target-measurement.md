# OpenDICE Target Measurement

This track converts the bundled FADGI/OpenDICE sample from ordinary codec test
imagery into a measurement made by FADGI's own analysis application.

## Scope

OpenDICE 3.00 implements the 2023 FADGI guidelines and reports target-based
measures such as tone response, uniformity, registration, noise, and resolution
where the selected target supports them. FADGI states that OpenDICE is intended
for conformance measurement and that results are only as valid as the target
image and reference measurements supplied to it.

Running the public sample proves that the repository can reproduce an official
target-analysis workflow. It does not measure this project's camera, lens,
light, RAW61 capture, PixelShift merge, or JPEG XL break-even. That would
require a target photographed through the actual acquisition system.

## Required Software

- FADGI OpenDICE Command Line 3.00 for Windows
- MATLAB Runtime 9.13 (R2022b), matching the release used to compile OpenDICE
- `Config_materials2023.txt`, the sample TIFF, and its matching density profile

Official downloads and manuals are on the
[FADGI OpenDICE page](https://www.digitizationguidelines.gov/guidelines/digitize-OpenDice.html).
MATLAB Runtime is free but is a separate, large installation. It is deliberately
not downloaded or installed by this repository.

## Current Execution Status

The official Windows command-line release was run locally on 2026-09-03 with
MATLAB Runtime 9.13 installed. Both the bundled text inputs and the official
Windows XLSX configuration/profile reached OpenDICE, but material `11` exited
with code `249` and this internal error:

```text
Unable to resolve the name 'handles.material'.
Error in OpenDICECommand (line 435)
```

Control probes show that argument parsing and target identification work:
material `1` reports that the image requires material `11`, while material `10`
reports that the selected target is unsupported. Material `11`, which target
`12` requires, is the branch that fails. This is therefore recorded as a
reproducible OpenDICE Command Line 3.00 limitation, not a target measurement.
The official GUI 3.01 is the bounded fallback; no exported OpenDICE result has
yet been produced.

## Reproducible Command

The wrapper selects material `11` (photographic negatives, 35mm to 4x5), FADGI
level `4`, target `12` (Negative Small 35mm 2), and `-e` for all RGB components.

```powershell
python scripts\download_testdata.py --direct-only

python scripts\run_opendice_sample.py `
  --executable "C:\path\to\OpenDICECommandv3.0_win.exe"
```

Use `--dry-run` to inspect the exact OpenDICE command without executing it. A
real run writes the OpenDICE export, `opendice.log`, and a hash-bound
`run_manifest.json` under `results/opendice_sample_measurement/`.

When the known material-11 failure occurs, the manifest records
`opendice_3_00_material_11_failure: true` and the wrapper exits with a specific
diagnosis instead of presenting the failure as a missing runtime.

## Publication Rule

The report must say **OpenDICE sample-target measurement**, not "FADGI
certified" or "camera system conforms to FADGI." The downloaded TIFF was made
elsewhere and has no paired RAW61/PS16 acquisition, so its results remain a
public reproducibility and analysis-method check rather than evidence in the
core archive-value break-even table.
