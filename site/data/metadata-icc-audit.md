# Metadata and ICC preservation audit

This closes the reporting gap in issue #3: a documented diff workflow, a field-retention table, and a sidecar recommendation. It combines the released scan evidence with a separate synthetic round trip. It does not certify an entire archive, every metadata field or every application.

## Scope and measured findings

The report binds 160 rendered-JXL candidates, 16 real-image lossless pilots and 32 historical DNG source/candidate pairs (16 each at lossless and d=0.01). The existing evidence is reused for those exact hashes. The synthetic test is new, uses fictional metadata and a generated 64×64 RGB16 TIFF, and requires no private scans.

| Information | Rendered TIFF → PPM → JXL | JXL inside DNG | Decoded files / separate retention |
| --- | --- | --- | --- |
| ICC color interpretation | Supplied explicitly to the encoder. Real-image lossless pilots pass the profile check. The synthetic lossless profile is byte-exact; lossy decoding returns a different matrix/TRC profile. | Camera interpretation is checked through selected DNG fields; camera samples are not assigned a display ICC. | Use the decoder's actual profile. PPM needs an ICC sidecar. Do not relabel lossy decoded pixels with the original TIFF profile. |
| Camera, lens, exposure, orientation, dates | Source-present fields in the curated list are explicitly copied and checked in all 160 final candidates. | The existing DNG audit includes camera make/model, but is not a complete EXIF/XMP audit. | The tested PNG keeps the JXL's photographic tags; PPM does not. Verify other exporters separately. |
| XMP lens information and creation date | `XMP-aux:LensInfo` and `XMP-xmp:CreateDate` were repaired in all 160 retained candidates. | Arbitrary XMP is outside the selected DNG audit. | Keep separate EXIF/XMP identities in comparisons. |
| Authorship, copyright, description | Copied when available, including author information repaired in 40 candidates. | No blanket preservation assertion for these fields. | Retain privately; review each public derivative. Copying selected tags is not anonymization. |
| Keywords, title, arbitrary XMP/IPTC | Not in the curated list. The synthetic title and keyword are omitted by the PPM-input workflow. IPTC fields absent from the fixture remain untested. | Outside the selected audit. | Retain an XMP sidecar or catalogue export, plus a private source metadata snapshot. |
| DNG raw geometry and color fields | Rendering bakes in raw processing; this workflow deliberately does not transfer DNG-only tags to the rendered JXL. | No preservation-review differences in 32 pairs for the selected fields listed below. | Keep the DNG for later raw processing; sidecar tags cannot turn rendered RGB back into raw data. |
| Encoder/container fields | Compression, strip layout, software and resolution tags may change or not be exposed in the candidate's EXIF view. | Version/backward version, compression, tiling, segment count, software and JXL settings change as expected. | Record versions and recipes; structural differences are not automatically metadata loss. |
| Maker notes and untested fields | No complete retention claim. | No complete retention claim. | Keep original RAW/DNG files and a private metadata snapshot. A tag absent from both files is untested, not “preserved”. |
| Capture notes and provenance | Not supplied automatically by the image codec. | Not supplied automatically by compression. | Keep source/master identities, scan notes, settings and checksums in a manifest. Historical encode-time input hashes cannot be reconstructed retrospectively. |

The curated list is defined by `TAGS` in `scripts/rebuild_verified_report.py`: make/model, orientation, lens make/model/info, focal length, aperture, exposure, ISO, original and creation dates (EXIF and XMP), subsecond dates, artist, copyright and description. Only source-present tags are compared. The release lists the fields actually repaired in each candidate; all 160 metadata repairs preserve the image codestream.

The DNG preservation-review list in `scripts/run_dng_jxl_verification.py` covers shape, active crop, photometric interpretation, bit depth, white level, camera identity, calibration illuminants, as-shot neutral, color/calibration/reduction/forward matrices, profile name, ICC field and opcode list 2. It does **not** claim a complete DNG-tag, maker-note, black-level, EXIF or XMP audit. Values absent in both source and candidate establish no retention evidence.

## Reproduce the synthetic round trip

Use the Python environment described in the report's reproduction instructions, libjxl 0.11.2 and ExifTool. The published pilot used ExifTool 13.12, NumPy 2.5.3, Pillow 12.3.0 and tifffile 2026.8.23; these exact versions and tool hashes are recorded in `data/metadata-evidence.json`. The main image measurements remain bound to their original environment, including tifffile 2026.9.15. Fixture file hashes can differ when writers insert timestamps; compare preservation states and decoded pixels/profile as well as versions.

From the repository root, choose a **new** work directory and output filename:

```powershell
.\.venv\Scripts\python.exe scripts/audit_metadata_roundtrip.py smoke `
  --tools '<libjxl-0.11.2-bin>' `
  --exiftool '<ExifTool.exe>' `
  --work results/metadata-audit/reproduction-01 `
  --output results/metadata-audit/reproduction-01.json
```

The script creates a TIFF with an embedded regression ICC and fictional EXIF/XMP/GPS fields, writes identical RGB16 pixels to PPM, encodes at lossless and d=0.05, explicitly copies the source-present curated tags, and decodes to PPM + ICC and 16-bit PNG. It fails if a curated field changes or if the lossless pixels/profile fail their exact checks. A field diff records `preserved`, `changed`, `missing` or `added`; source values and absolute paths are omitted from the JSON.

The fresh pilot preserved all 15 fixture fields selected by the curated list at both distances. PPM retained none of the JXL's 24 ExifTool-reported photographic fields; PNG retained all 24. The title, keyword and GPS fields were not copied to JXL. These are bounded workflow results, not claims about every JPEG XL encoder or application.

ExifTool's photographic-tag view does not expose the compressed JXL codestream ICC. A missing ICC in an ExifTool listing is therefore **not** evidence that the profile was discarded. The pilot excludes ICC from tag differences and reads it independently with `djxl --icc_out`. It checks both byte identity and the matrix/TRC interpretation. For the lossy fixture, both differ from the source; the decoder's profile must travel with its decoded samples.

## Compare real DNG, TIFF, JXL and decoded files

To regenerate the report section after an editorial change, using unchanged public measurements and the committed synthetic evidence:

```powershell
.\.venv\Scripts\python.exe scripts/build_verified_release.py --refresh-public --source-ref report-2026-09-17-metadata-audit
.\.venv\Scripts\python.exe scripts/render_verified_report.py
.\.venv\Scripts\python.exe scripts/check_verified_release.py
```

The refresh rejects changes to the scientific code, existing evidence and image/pixel assets. It updates documentation and report-code hashes, and rebinds the CSV to the new report identity without changing measurement values. A changed scientific experiment requires its own rebuild.

The same diff command accepts any two files readable by ExifTool and never modifies them. Run it for each transition rather than assuming that a successful encode preserves metadata:

```powershell
.\.venv\Scripts\python.exe scripts/audit_metadata_roundtrip.py diff `
  --source '<source.dng>' --candidate '<rendered-master.tif>' `
  --exiftool '<ExifTool.exe>' --output results/metadata-audit/dng-to-tiff.json
.\.venv\Scripts\python.exe scripts/audit_metadata_roundtrip.py diff `
  --source '<rendered-master.tif>' --candidate '<master.jxl>' `
  --exiftool '<ExifTool.exe>' --output results/metadata-audit/tiff-to-jxl.json
.\.venv\Scripts\python.exe scripts/audit_metadata_roundtrip.py diff `
  --source '<master.jxl>' --candidate '<decoded.png>' `
  --exiftool '<ExifTool.exe>' --output results/metadata-audit/jxl-to-decoded.json
```

`missing` means that ExifTool did not report that field in the selected EXIF/XMP/IPTC/maker-note view. This includes structural tags that are not meaningful in the output container. Inspect changed fields locally to decide whether they are expected, need copying or require separate retention. The DNG scientific audit remains the source for raw-interpretation fields; this generic diff is not a substitute for it.

For a private full inspection and ICC extraction:

```powershell
& '<ExifTool.exe>' -j -G1 -a -s -struct '<source.dng>' |
  Set-Content -Encoding utf8 results/metadata-audit/source-metadata.private.json
& '<djxl.exe>' '<master.jxl>' results/metadata-audit/decoded.ppm `
  --bits_per_sample=16 --icc_out=results/metadata-audit/decoded.icc
```

Keep full metadata dumps under an ignored private directory: they can contain identity, GPS, serial identifiers, local paths and descriptive text. For a TIFF export, embed `decoded.icc` with the decoded pixels using a writer that supports ICC, explicitly restore intended photographic tags, and repeat the diff. Merely copying the original TIFF's ICC onto different decoded sample values is incorrect.

## Recommended sidecar package

Keep the image master plus:

1. `master.xmp`, or a catalogue export, for titles, keywords, rights, ratings and other application metadata not covered by the curated copy. Verify which fields the intended applications actually read.
2. `source-metadata.private.json`, a private full ExifTool snapshot, and the original RAW/DNG for information that cannot be round-tripped through XMP. A JSON snapshot is an audit record, not an automatically restorable image sidecar.
3. `master.archive.json`, a manifest connecting the master to source hashes, capture notes, rendering/inversion settings, tool versions and accompanying files. Keep the actual `.pp3`/other recipes with their hashes, rather than only naming a preset.
4. `decoded.icc` alongside PPM or any working format that cannot embed color interpretation. Keep the source ICC with source-render provenance when useful, clearly distinguished from the decoder's ICC.

An illustrative manifest (replace placeholders locally; never invent historical hashes):

```json
{
  "schema": 1,
  "master": {"file": "frame.jxl", "sha256": "<measured SHA-256>", "bytes": 0},
  "sources": [{"file": "frame.dng", "sha256": "<measured SHA-256>"}],
  "sidecars": [{"file": "frame.xmp", "sha256": "<measured SHA-256>", "bytes": 0}],
  "render_recipe": {"file": "neutral-render.pp3", "sha256": "<measured SHA-256>"},
  "tools": {"encoder": "cjxl 0.11.2", "metadata": "ExifTool 13.12"},
  "capture_notes": {"film": "<film stock>", "light": "<light source>", "lens": "<lens and aperture>"},
  "privacy": "private archive; prepare and inspect separate publication copies"
}
```

Count the required sidecars and manifest in a production storage budget. The report's present JXL comparison includes the photographic metadata embedded in each final file and records zero required external sidecars for that measured image workflow. It does **not** include the additional archive package recommended here; adding it requires recalculating byte thresholds.

Before sharing, inspect GPS, serial identifiers, owner/author information, dates, descriptions, keywords, embedded previews and local paths. Export an intentionally limited public manifest instead of publishing the private package. Metadata retention and publication safety are different decisions.
