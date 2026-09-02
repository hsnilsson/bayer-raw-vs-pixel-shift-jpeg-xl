from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path[:0] = [str(SRC), str(SCRIPTS)]

from make_break_even_review_panels import local_align_raw61  # noqa: E402
from make_break_even_review_viewers import display_range, html_page, save_display  # noqa: E402
from run_public_latitude_stress import build_transforms  # noqa: E402


VIEWER_DATA_RE = re.compile(
    r'<script type="application/json" id="cropViewerData">(.*?)</script>', re.DOTALL
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_crop(path: Path, crop: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = crop
    with Image.open(path) as image:
        return np.asarray(image.crop((x, y, x + width, y + height))).copy()


def load_published_viewers(site_path: Path) -> list[Path]:
    match = VIEWER_DATA_RE.search(site_path.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"Could not find cropViewerData in {site_path}")
    entries = json.loads(match.group(1))
    viewers = []
    for entry in entries:
        reference = Path(entry["reference"])
        viewers.append(site_path.parent / reference.parent / "metadata.json")
    return viewers


def load_render_index(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return {
        (row.get("scan_set", ""), row.get("set_id", ""), row.get("role", "")): row
        for row in rows
    }


def registration_metadata(path: Path) -> dict[str, object]:
    sidecar = path.with_suffix(".registration.json")
    if not sidecar.is_file():
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8"))


def audit_viewer(
    metadata_path: Path,
    render_index: dict[tuple[str, str, str], dict[str, str]],
    repair: bool,
) -> dict[str, object]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    scan_set = str(metadata["scan_set"])
    set_id = str(metadata["set_id"])
    crop_name = str(metadata["crop_name"])
    crop_spec = tuple(int(value) for value in metadata["crop"])
    sources = metadata["build_inputs"]["sources"]
    reference_path = ROOT / sources["ps16"]["path"]
    raw61_registered_path = ROOT / sources["raw61_registered"]["path"]
    published_path = metadata_path.parent / metadata["images_by_transform"]["identity"]["raw61"]

    raw_row = render_index.get((scan_set, set_id, "raw61"), {})
    ps16_row = render_index.get((scan_set, set_id, "ps16"), {})
    raw_source = str(raw_row.get("source", ""))
    ps16_source = str(ps16_row.get("source", ""))
    provenance_checks = {
        "raw_render_source_is_arw": raw_source.lower().endswith(".arw"),
        "ps16_render_source_is_dng": ps16_source.lower().endswith(".dng"),
        "reference_exists": reference_path.is_file(),
        "raw61_registered_exists": raw61_registered_path.is_file(),
        "published_exists": published_path.is_file(),
    }

    registration = registration_metadata(raw61_registered_path)
    candidate_shape = registration.get("candidate_shape", [])
    reference_shape = registration.get("reference_shape", [])
    provenance_checks["registration_has_lower_resolution_candidate"] = bool(
        len(candidate_shape) >= 2
        and len(reference_shape) >= 2
        and int(candidate_shape[0]) * int(candidate_shape[1])
        < int(reference_shape[0]) * int(reference_shape[1])
    )

    result: dict[str, object] = {
        "scan_set": scan_set,
        "set_id": set_id,
        "crop_name": crop_name,
        "raw_source": raw_source,
        "ps16_source": ps16_source,
        "provenance_checks": provenance_checks,
        "registration_candidate_shape": candidate_shape,
        "registration_reference_shape": reference_shape,
        "status": "unverified",
        "repaired": False,
    }
    if not all(provenance_checks.values()):
        return result

    reference_crop = read_crop(reference_path, crop_spec)
    raw61_crop = read_crop(raw61_registered_path, crop_spec)
    aligned_raw61, alignment = local_align_raw61(reference_crop, raw61_crop, 32.0)
    transforms = {item.name: item for item in build_transforms(reference_crop)}
    identity_levels = display_range(transforms["identity"].apply(reference_crop))
    reproduced_path = metadata_path.parent / ".raw61-audit.png"
    save_display(
        reproduced_path,
        transforms["identity"].apply(aligned_raw61),
        1024,
        force=True,
        levels=identity_levels,
    )
    published_hash = sha256(published_path)
    reproduced_hash = sha256(reproduced_path)
    exact_match_before_repair = published_hash == reproduced_hash
    reproduced_path.unlink()

    if repair and not exact_match_before_repair:
        for view_mode in metadata["view_modes"]:
            transform_name = view_mode["key"]
            transform = transforms[transform_name]
            reference_levels = display_range(transform.apply(reference_crop))
            filename = metadata["images_by_transform"][transform_name]["raw61"]
            save_display(
                metadata_path.parent / filename,
                transform.apply(aligned_raw61),
                1024,
                force=True,
                levels=reference_levels,
            )
        metadata["local_raw61_alignment"] = {
            "shift_x_px": alignment.shift_x_px,
            "shift_y_px": alignment.shift_y_px,
            "confidence": alignment.confidence,
            "applied": alignment.applied,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        title = f"{scan_set} / {set_id} / {crop_name}"
        identity_images = metadata["images_by_transform"]["identity"]
        (metadata_path.parent / "index.html").write_text(
            html_page(title, identity_images, metadata), encoding="utf-8"
        )
        result["repaired"] = True

    final_hash = sha256(published_path)
    result.update(
        published_sha256_before=published_hash,
        reproduced_sha256=reproduced_hash,
        published_sha256_after=final_hash,
        exact_match_before_repair=exact_match_before_repair,
        exact_match_after_repair=final_hash == reproduced_hash,
        local_alignment={
            "shift_x_px": alignment.shift_x_px,
            "shift_y_px": alignment.shift_y_px,
            "confidence": alignment.confidence,
            "applied": alignment.applied,
        },
        status="verified" if final_hash == reproduced_hash else "mismatch",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that every published RAW61 viewer crop is reproducible from its ARW-derived registered TIFF."
    )
    parser.add_argument("--site", type=Path, default=ROOT / "site/index.html")
    parser.add_argument(
        "--render-index",
        type=Path,
        default=ROOT / "outputs/rawtherapee_renders/rawtherapee_render_index.csv",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()

    render_index = load_render_index(args.render_index)
    results = []
    for path in load_published_viewers(args.site):
        try:
            results.append(audit_viewer(path, render_index, args.repair))
        except Exception as exc:  # Keep the audit running so every broken case is reported.
            metadata = json.loads(path.read_text(encoding="utf-8"))
            results.append(
                {
                    "scan_set": metadata.get("scan_set", ""),
                    "set_id": metadata.get("set_id", ""),
                    "crop_name": metadata.get("crop_name", ""),
                    "status": "unverified",
                    "repaired": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    summary = {
        "published_viewers": len(results),
        "verified": sum(item["status"] == "verified" for item in results),
        "repaired": sum(bool(item["repaired"]) for item in results),
        "unverified": sum(item["status"] == "unverified" for item in results),
        "mismatch": sum(item["status"] == "mismatch" for item in results),
    }
    payload = {"summary": summary, "viewers": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    for item in results:
        print(
            item["status"],
            "repaired" if item["repaired"] else "unchanged",
            item["scan_set"],
            item["set_id"],
            item["crop_name"],
        )
    return 0 if summary["unverified"] == 0 and summary["mismatch"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
