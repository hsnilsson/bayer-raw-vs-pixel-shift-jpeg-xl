"""Independent metadata section derived from the bound release evidence."""
from collections import Counter
from html import escape


def metadata_section(release, attachments, table):
    candidates = release["candidates"]
    frames = release["frames"]
    audit = attachments["metadata"]
    dng = attachments["dng"]
    repairs = Counter(field for row in candidates for field in row["metadata_repaired_fields"])
    fields = ", ".join(f"<code>{escape(k)}</code> ({v} files)" for k, v in sorted(repairs.items()))
    pilots = sum(all(f["lossless_pilot"].get(k) for k in ("pixel_exact", "icc_equivalent", "metadata_exact")) for f in frames)
    checked = sum(r["metadata_pass"] for r in candidates)
    dng_records = [r for route in dng["routes"] for r in route["records"]]
    dng_pass = sum(r["technical_pass"] for r in dng_records)
    rows = [
        ["Rendered-image ICC profile", "Lossless pilots retain the checked color interpretation. Lossy decoding can return a different ICC profile.",
         "Keep the profile produced by the decoder with its pixels. Use a color-managed conversion; do not attach the source TIFF profile to different decoded sample values."],
        ["Camera, lens, exposure, orientation and capture dates", f"{checked}/{len(candidates)} released JXLs pass the curated source-tag comparison. Only fields present in the source render can be preserved.",
         "Keep EXIF in the JXL container. Recheck tags after exporting to another format."],
        ["Selected XMP: lens information and creation date", "Explicitly copied and checked alongside EXIF; metadata repair was needed in the retained encodes.",
         "Preserve the grouped tag names; EXIF and XMP dates are separate fields."],
        ["Authorship, copyright and description", "Copied when present in the source render. This does not make a file safe to publish.",
         "Retain privately; review rights and identity information in every public derivative."],
        ["Other XMP/IPTC, keywords and catalogue notes", "Outside the curated copy list. The synthetic title and keyword disappear in the PPM-input route.",
         "Keep an XMP sidecar or catalogue export and a private metadata snapshot. Test any additional fields needed by the archive."],
        ["DNG camera interpretation", f"{dng_pass}/{len(dng_records)} file pairs pass the existing selected-field audit across lossless and d=0.01. DNG version, compression, tiling and encoder fields change as expected.",
         "Keep the DNG container for raw processing. A rendered JXL does not replace its camera matrices, white balance, raw geometry or processing instructions."],
        ["Maker notes and fields outside the DNG audit", "No complete preservation claim. Absence from both compared files is not evidence of successful retention.",
         "Retain original RAW/DNG files and a private metadata dump for information that cannot be represented or has not been checked."],
        ["Decoded working files", "The tested PPM has no photographic tags and needs a separate ICC. The tested 16-bit PNG retains the JXL's EXIF/XMP tags and carries a decoded profile.",
         "Treat PPM + ICC as a pair. Verify another decoder or TIFF export before making it an archival master."],
        ["Capture notes and provenance", "Hashes and recipes identify the report's retained artifacts; historical encode-time input hashes remain unavailable.",
         "Keep source-to-master relationships, capture notes, render settings, tool versions and checksums in an archive manifest."],
    ]
    smoke_rows = []
    for row in audit["records"]:
        selected = row["curated_fields_after_copy"]
        smoke_rows.append(["Lossless" if row["distance"] == 0 else f'd={row["distance"]:g}',
                           f'{selected["counts"].get("preserved", 0)}/{len(selected["fields"])}',
                           "Exact" if row["icc"]["byte_exact"] else "Different decoded profile",
                           row["jxl_to_decoded_ppm"]["counts"].get("preserved", 0),
                           row["jxl_to_decoded_png"]["counts"].get("preserved", 0)])
    return ('<details id="metadata"><summary>Metadata and ICC preservation</summary>'
            '<p>A compact master needs both interpretable pixels and the information that connects them to the capture. '
            'This audit separates the rendered-JXL route, the DNG container and temporary decoded files.</p>'
            + table(["Information", "What the audit establishes", "What to retain or do"], rows, "Preserved, omitted and separately retained information")
            + f'<p><strong>Evidence from the retained scans:</strong> {pilots}/{len(frames)} real-image lossless pilots pass pixel, ICC and selected metadata checks. '
            f'All {len(candidates)} original/repaired image codestreams match in the lineage audit. The repair changed metadata, and its final file bytes are included in the storage comparison.</p>'
            + '<p><strong>Fields repaired:</strong> ' + fields + '.</p>'
            + table(["Synthetic route", "Curated tags retained", "ICC from djxl", "JXL tags retained in PPM", "JXL tags retained in PNG"],
                    smoke_rows, "Fresh 64×64 RGB16 fixture with fictional metadata; cjxl/djxl 0.11.2")
            + '<p>The synthetic test uses the same PPM input and explicit metadata-copy method as the report. '
            'Its field counts cover this fixture only. The tag diff excludes ICC because ExifTool does not expose the JXL codestream profile in that view; '
            'the separate decoder-profile check establishes the ICC result. Untested application paths and fields are not covered.</p>'
            '<p><strong>Recommended archive package:</strong> the JXL or DNG master, an XMP sidecar for catalogue fields, '
            'a private metadata snapshot, and a manifest with source hashes, render settings and capture notes. '
            'Keep a decoded ICC beside every intermediate format that cannot embed it. Required sidecar bytes must be added when budgeting such a package; '
            'the current tables measure JXL files with the checked photographic metadata and do not claim to include this proposed archive package.</p>'
            '<p><strong>Public copies:</strong> inspect author/owner information, dates, GPS, serial identifiers, descriptions, keywords and local paths. '
            'The curated copy is not an anonymization filter: it can deliberately retain author and capture information.</p>'
            '<p><a href="data/metadata-icc-audit.md">Full audit, reproducible diff commands and sidecar example</a> · '
            '<a download href="data/metadata-evidence.json">Synthetic metadata evidence JSON</a> · '
            '<a href="data/lineage-evidence.json">Retained-file lineage audit</a> · '
            '<a href="data/dng-evidence.json">DNG field differences</a></p></details>')
