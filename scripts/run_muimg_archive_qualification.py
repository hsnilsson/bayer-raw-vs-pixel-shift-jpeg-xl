from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "input"
DEFAULT_CROP_PLAN = ROOT / "results/break_even_crop_guides/crop_plan.json"
DEFAULT_OUTPUT = Path(r"D:\jpegxl-muimg-qualification")
DEFAULT_MUIMG = Path(r"D:\jpegxl-muimg-tools\venv\Scripts\muimg.exe")


@dataclass(frozen=True)
class QualificationCase:
    scan_set: str
    set_id: str
    source_dng: Path
    raw61: Path
    crop_case: str

    @property
    def slug(self) -> str:
        value = re.sub(r"[^a-z0-9]+", "_", self.scan_set.lower()).strip("_")
        return value or "scan"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def discover_cases(input_root: Path, crop_plan: Path) -> tuple[list[QualificationCase], list[str]]:
    plan = read_json(crop_plan)
    crop_cases = plan.get("cases", {})
    if not isinstance(crop_cases, dict):
        raise ValueError(f"crop plan has no cases object: {crop_plan}")

    cases: list[QualificationCase] = []
    skipped: list[str] = []
    seen_sources: set[Path] = set()
    for manifest_path in sorted(input_root.rglob("scan_manifest.json")):
        manifest = read_json(manifest_path)
        scan_set = str(manifest.get("scan_root_name") or manifest_path.parent.name)
        captures = manifest.get("capture_sets", [])
        if not isinstance(captures, list):
            continue
        for capture in captures:
            if not isinstance(capture, dict) or not capture.get("pixelshift16_dng"):
                continue
            set_id = str(capture.get("set_id", ""))
            source = manifest_path.parent / str(capture["pixelshift16_dng"])
            raw_name = capture.get("single_raw")
            raw61 = manifest_path.parent / str(raw_name) if raw_name else Path()
            crop_case = f"{scan_set}|{set_id}"
            reason = None
            if capture.get("storage_budget_role") != "primary_candidate":
                reason = "not a paired primary candidate"
            elif not source.is_file():
                reason = "source DNG is missing (stale manifest entry)"
            elif not raw_name or not raw61.is_file():
                reason = "paired RAW61 is missing"
            elif crop_case not in crop_cases:
                reason = "no reviewed crop plan"
            elif source.resolve() in seen_sources:
                reason = "duplicate source DNG"
            if reason:
                skipped.append(f"{crop_case}: {reason}")
                continue
            seen_sources.add(source.resolve())
            cases.append(QualificationCase(scan_set, set_id, source, raw61, crop_case))
    return cases, skipped


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def case_dir(output_root: Path, case: QualificationCase) -> Path:
    return output_root / case.slug / case.set_id


def candidate_path(output_root: Path, case: QualificationCase, level: str) -> Path:
    return case_dir(output_root, case) / "adc_jxl_dng" / level / case.source_dng.name


def encode_fingerprint(case: QualificationCase, distance: float, effort: int, preview_reduce: int) -> dict[str, Any]:
    stat = case.source_dng.stat()
    return {
        "source": str(case.source_dng.resolve()),
        "source_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "distance": distance,
        "effort": effort,
        "preview_reduce": preview_reduce,
    }


def encode_case(
    case: QualificationCase,
    *,
    output_root: Path,
    muimg: Path,
    level: str,
    distance: float,
    effort: int,
    preview_reduce: int,
) -> dict[str, Any]:
    output = candidate_path(output_root, case, level)
    output.parent.mkdir(parents=True, exist_ok=True)
    record_path = output.parent / "encode.json"
    fingerprint = encode_fingerprint(case, distance, effort, preview_reduce)
    if output.is_file() and output.stat().st_size > 0 and record_path.is_file():
        previous = read_json(record_path)
        if previous.get("fingerprint") == fingerprint and previous.get("candidate_sha256") == sha256_file(output):
            return previous | {"status": "reused"}

    command = [
        str(muimg),
        "dng",
        "copy",
        str(case.source_dng),
        str(output),
        "--jxl-distance",
        str(distance),
        "--jxl-effort",
        str(effort),
        "--preview",
        "--preview-reduce",
        str(preview_reduce),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    result = {
        "scan_set": case.scan_set,
        "set_id": case.set_id,
        "source_dng": str(case.source_dng),
        "raw61": str(case.raw61),
        "candidate": str(output),
        "fingerprint": fingerprint,
        "command": command,
        "seconds": round(time.perf_counter() - started, 3),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "status": "failed",
    }
    if completed.returncode == 0 and output.is_file() and output.stat().st_size > 0:
        result.update(
            {
                "status": "encoded",
                "candidate_bytes": output.stat().st_size,
                "candidate_mib": round(output.stat().st_size / 2**20, 4),
                "raw61_mib": round(case.raw61.stat().st_size / 2**20, 4),
                "candidate_pct_raw61": round(output.stat().st_size / case.raw61.stat().st_size * 100, 2),
                "candidate_sha256": sha256_file(output),
            }
        )
    record_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def run_verification(
    case: QualificationCase,
    *,
    output_root: Path,
    level: str,
    crop_plan: Path,
    maxworkers: int,
) -> dict[str, Any]:
    root = case_dir(output_root, case)
    out_dir = root / "verification"
    command = [
        sys.executable,
        str(ROOT / "scripts/run_dng_jxl_verification.py"),
        "--scan-root",
        str(root),
        "--out-dir",
        str(out_dir),
        "--source",
        f"{case.source_dng}={case.scan_set}/{case.set_id}",
        "--level",
        level,
        "--crop-plan",
        str(crop_plan),
        "--crop-case",
        case.crop_case,
        "--patch-size",
        "64",
        "--maxworkers",
        str(maxworkers),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    result: dict[str, Any] = {
        "status": "failed",
        "seconds": round(time.perf_counter() - started, 3),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "output": str(out_dir),
    }
    if completed.returncode != 0:
        return result

    with (out_dir / "summary.csv").open(newline="", encoding="utf-8-sig") as handle:
        summary = list(csv.DictReader(handle))
    with (out_dir / "patch_summary.csv").open(newline="", encoding="utf-8-sig") as handle:
        patches = list(csv.DictReader(handle))
    with (out_dir / "metadata_diff_summary.csv").open(newline="", encoding="utf-8-sig") as handle:
        metadata = list(csv.DictReader(handle))
    identity = next(row for row in summary if row["level"] == level and row["transform"] == "identity")
    stress = next(
        row for row in patches if row["level"] == level and row["transform"] == "negative_density_hard_print"
    )
    preservation_changes = sum(
        int(row["changes"])
        for row in metadata
        if row["level"] == level and row["interpretation"] == "review_preservation_change"
    )
    result.update(
        {
            "status": "verified",
            "mean_structure_loss": float(identity["mean_structure_loss"]),
            "worst_structure_loss": float(identity["worst_structure_loss"]),
            "stress_p95_delta_e00": float(stress["p95_delta_e00"]),
            "stress_max_delta_e00": float(stress["max_delta_e00"]),
            "preservation_review_changes": preservation_changes,
        }
    )
    return result


def full_segment_decode(path: Path, maxworkers: int) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_dng_jxl_verification import find_main_image, import_tifffile

    started = time.perf_counter()
    segments = 0
    samples = 0
    with import_tifffile().TiffFile(path) as tif:
        main = find_main_image(tif)
        expected_segments = len(main.page.dataoffsets)
        for decoded, _, _ in main.page.segments(maxworkers=maxworkers):
            if decoded is None:
                raise ValueError(f"decoder returned an empty segment: {path}")
            segments += 1
            samples += int(decoded.size)
    if segments != expected_segments:
        raise ValueError(f"decoded {segments} of {expected_segments} segments: {path}")
    return {
        "status": "decoded",
        "segments": segments,
        "decoded_samples_including_tile_padding": samples,
        "seconds": round(time.perf_counter() - started, 3),
    }


def build_summary(records: list[dict[str, Any]], skipped: list[str], size_limit_mib: float) -> dict[str, Any]:
    failures = [record for record in records if record.get("qualification") != "pass"]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "pass" if records and not failures else "fail",
        "gates": {
            "maximum_candidate_mib": size_limit_mib,
            "maximum_stress_p95_delta_e00": 1.0,
            "maximum_worst_structure_loss": 1.0,
            "maximum_preservation_review_changes": 0,
            "full_segment_decode_required": True,
        },
        "summary": {
            "cases": len(records),
            "passed": len(records) - len(failures),
            "failed": len(failures),
            "skipped_manifest_entries": len(skipped),
        },
        "skipped": skipped,
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify muimg DNG/JXL as a space-limited PS16 archive candidate.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--crop-plan", type=Path, default=DEFAULT_CROP_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--muimg", type=Path, default=DEFAULT_MUIMG)
    parser.add_argument("--level", default="d001")
    parser.add_argument("--distance", type=float, default=0.01)
    parser.add_argument("--effort", type=int, default=7)
    parser.add_argument("--preview-reduce", type=int, choices=(1, 2, 4, 8), default=8)
    parser.add_argument("--encode-jobs", type=int, default=3)
    parser.add_argument("--decode-workers", type=int, default=4)
    parser.add_argument("--size-limit-mib", type=float, default=200.0)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)

    cases, skipped = discover_cases(args.input_root, args.crop_plan)
    print(f"Qualified case plan: {len(cases)} case(s); {len(skipped)} skipped manifest entry/entries")
    for case in cases:
        print(f"  {case.crop_case}: {case.source_dng.name}")
    for item in skipped:
        print(f"  skipped: {item}")
    if args.plan:
        return 0
    if not args.muimg.is_file():
        raise SystemExit(f"muimg executable not found: {args.muimg}")
    if args.encode_jobs <= 0 or args.decode_workers <= 0:
        raise SystemExit("worker counts must be positive")

    encoded: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.encode_jobs) as pool:
        futures = {
            pool.submit(
                encode_case,
                case,
                output_root=args.output_root,
                muimg=args.muimg,
                level=args.level,
                distance=args.distance,
                effort=args.effort,
                preview_reduce=args.preview_reduce,
            ): case
            for case in cases
        }
        for future in as_completed(futures):
            case = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # keep the batch auditable after one failure
                record = {"status": "failed", "error": str(exc)}
            encoded[case.crop_case] = record
            print(f"encoded {case.crop_case}: {record.get('status')}", flush=True)

    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        encode = encoded[case.crop_case]
        record: dict[str, Any] = {"scan_set": case.scan_set, "set_id": case.set_id, "encode": encode}
        if encode.get("status") not in {"encoded", "reused"}:
            record["qualification"] = "fail"
            record["reasons"] = ["encoding failed"]
            records.append(record)
            continue
        candidate = candidate_path(args.output_root, case, args.level)
        print(f"[{index}/{len(cases)}] verifying {case.crop_case}", flush=True)
        try:
            verification = run_verification(
                case,
                output_root=args.output_root,
                level=args.level,
                crop_plan=args.crop_plan,
                maxworkers=args.decode_workers,
            )
        except Exception as exc:
            verification = {"status": "failed", "error": str(exc)}
        try:
            decode = full_segment_decode(candidate, args.decode_workers)
        except Exception as exc:
            decode = {"status": "failed", "error": str(exc)}
        reasons = []
        if verification.get("status") != "verified":
            reasons.append("crop/metadata verification failed")
        else:
            if float(verification["stress_p95_delta_e00"]) > 1.0:
                reasons.append("hard-inversion color p95 exceeds 1 DeltaE00")
            if float(verification["worst_structure_loss"]) > 1.0:
                reasons.append("worst normalized structure error exceeds 1.0")
            if int(verification["preservation_review_changes"]) > 0:
                reasons.append("preservation-relevant DNG metadata changed")
        if decode.get("status") != "decoded":
            reasons.append("not every JXL main-image segment decoded")
        if float(encode.get("candidate_mib", float("inf"))) > args.size_limit_mib:
            reasons.append(f"candidate exceeds {args.size_limit_mib:g} MiB")
        record.update(
            {
                "verification": verification,
                "full_segment_decode": decode,
                "qualification": "pass" if not reasons else "fail",
                "reasons": reasons,
            }
        )
        records.append(record)

    result = build_summary(records, skipped, args.size_limit_mib)
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = args.output_root / "qualification.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(json.dumps(result["summary"], indent=2))
    return 0 if result["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
