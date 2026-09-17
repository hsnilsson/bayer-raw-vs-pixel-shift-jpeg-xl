"""Full-frame overview bindings shared by export and the publication gate."""
from __future__ import annotations

import os
from pathlib import Path
from incremental_cache import fingerprint


def overview_record(metadata, evidence):
    matches = [r for r in evidence["records"] if
               (r["scan_set"], r["set_id"], r["crop"]) ==
               (metadata["scan_set"], metadata["set_id"], metadata["crop_name"])]
    if len(matches) != 1:
        raise ValueError("Missing or duplicate full-frame overview record")
    record = matches[0]
    if record["crop_xywh"] != metadata["crop"] or record["recipe_sha256"] != fingerprint(metadata["browser_transform_recipe"]):
        raise ValueError("Overview crop or tone recipe mismatch")
    roles = set(metadata["asset_manifest"])
    modes = {m["key"] for m in metadata["view_modes"]}
    if set(record["sources"]) != roles:
        raise ValueError("Incomplete full-frame overview sources")
    for source in record["sources"].values():
        h, w, channels = source["source_shape"]
        if source["source_bounds"] != [0, 0, w, h] or channels != 3:
            raise ValueError("Overview must cover the full frame")
        if set(source["files"]) != modes:
            raise ValueError("Incomplete full-frame overview modes")
        if any(not p.startswith("assets/overviews-verified/") or ".." in Path(p).parts for p in source["files"].values()):
            raise ValueError("Overview must use a dedicated full-frame asset")
    return record


def bind_overviews(metadata, evidence, metadata_path, site):
    record = overview_record(metadata, evidence)
    modes = [m["key"] for m in metadata["view_modes"]]
    sets = {mode: {role: os.path.relpath(site / s["files"][mode], metadata_path.parent).replace("\\", "/")
                   for role, s in record["sources"].items()} for mode in modes}
    for sources in sets.values():
        sources["ps16_lossless"] = sources["reference"]
    metadata["overviews_by_transform"] = sets
    metadata["overviews"] = sets["identity"]
    metadata["overview_preview_generation"] = {
        "generator": "scripts/build_verified_overviews.py", "scope": "full_frame",
        "evidence_id": evidence["evidence_id"], "record_sha256": fingerprint(record),
        "method": evidence["method"]}


def verify_overview_binding(metadata, evidence, metadata_path, site):
    expected = dict(metadata)
    bind_overviews(expected, evidence, metadata_path, site)
    for field in ("overviews", "overviews_by_transform", "overview_preview_generation"):
        if metadata.get(field) != expected[field]:
            raise ValueError("Viewer full-frame overview binding mismatch: " + field)
