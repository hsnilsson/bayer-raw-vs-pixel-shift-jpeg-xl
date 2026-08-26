from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_local_scan_study as local_study  # noqa: E402
import run_storage_budget_index as budget_index  # noqa: E402
from jxl_levels import DEFAULT_LEVELS, require_level  # noqa: E402


DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_VERIFICATION_ROOT = ROOT / "results/dng_jxl_verification"
DEFAULT_OUTPUT_DIR = ROOT / "results/archival_break_even"
HARD_TRANSFORM = "negative_density_hard_print"


@dataclass
class RawLossRow:
    scan_set: str
    set_id: str
    raw61_color_delta_e00_p95_identity: float | None
    raw61_color_delta_e00_p95_stress: float | None
    raw61_channel_bias_max_stress: float | None
    raw61_clipping_delta_stress: float | None
    raw61_structure_loss: float | None
    notes: str


@dataclass
class StructureRow:
    scan_set: str
    set_id: str
    level: str
    scope: str
    raw61_structure_loss: float | None
    jxl_structure_loss: float | None
    artifact_risk: str
    structure_verdict: str
    notes: str


@dataclass
class BreakEvenRow:
    scan_set: str
    film_stock: str
    film_type: str
    shot_year: str
    set_id: str
    level: str
    retained_size_mib: float | None
    raw61_size_mib: float | None
    size_vs_raw61_pct: float | None
    size_status: str
    size_bracket: str
    color_delta_e00_p95_identity: float | None
    color_delta_e00_p95_stress: float | None
    channel_bias_max_stress: float | None
    raw61_color_delta_e00_p95_identity: float | None
    raw61_color_delta_e00_p95_stress: float | None
    color_verdict: str
    raw61_structure_loss: float | None
    jxl_structure_loss: float | None
    structure_verdict: str
    artifact_risk: str
    metadata_review_changes: int | None
    metadata_review_fields: str
    metadata_risk: str
    evidence_status: str
    verdict: str
    notes: str


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_csv_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text == "-":
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if math.isnan(result):
        return None
    return result


def parse_int(value: str | None) -> int | None:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def load_raw_loss(path: Path | None) -> dict[tuple[str, str], RawLossRow]:
    rows: dict[tuple[str, str], RawLossRow] = {}
    for row in read_csv_rows(path):
        item = RawLossRow(
            scan_set=row.get("scan_set", ""),
            set_id=row.get("set_id", ""),
            raw61_color_delta_e00_p95_identity=parse_float(
                row.get("raw61_color_delta_e00_p95_identity")
            ),
            raw61_color_delta_e00_p95_stress=parse_float(
                row.get("raw61_color_delta_e00_p95_stress")
            ),
            raw61_channel_bias_max_stress=parse_float(row.get("raw61_channel_bias_max_stress")),
            raw61_clipping_delta_stress=parse_float(row.get("raw61_clipping_delta_stress")),
            raw61_structure_loss=parse_float(row.get("raw61_structure_loss")),
            notes=row.get("notes", ""),
        )
        rows[(item.scan_set, item.set_id)] = item
    return rows


def load_structure(path: Path | None) -> dict[tuple[str, str, str], StructureRow]:
    rows: dict[tuple[str, str, str], StructureRow] = {}
    for row in read_csv_rows(path):
        item = StructureRow(
            scan_set=row.get("scan_set", ""),
            set_id=row.get("set_id", ""),
            level=row.get("level", ""),
            scope=row.get("scope", ""),
            raw61_structure_loss=parse_float(row.get("raw61_structure_loss")),
            jxl_structure_loss=parse_float(row.get("jxl_structure_loss")),
            artifact_risk=row.get("artifact_risk", ""),
            structure_verdict=row.get("structure_verdict", ""),
            notes=row.get("notes", ""),
        )
        rows[(item.scan_set, item.set_id, item.level)] = item
    return rows


def load_rendered_jxl_sizes(path: Path | None) -> dict[tuple[str, str, str], float]:
    rows: dict[tuple[str, str, str], float] = {}
    for row in read_csv_rows(path):
        key = (row.get("scan_set", ""), row.get("set_id", ""), row.get("level", ""))
        size = parse_float(row.get("encoded_mib"))
        if all(key) and size is not None and row.get("status") == "encoded_decoded":
            rows[key] = size
    return rows


def load_rendered_patch_summary(
    path: Path | None,
) -> dict[tuple[str, str, str], dict[str, dict[str, str]]]:
    rows: dict[tuple[str, str, str], dict[str, dict[str, str]]] = {}
    for row in read_csv_rows(path):
        key = (row.get("scan_set", ""), row.get("set_id", ""), row.get("level", ""))
        transform = row.get("transform", "")
        if all(key) and transform:
            rows.setdefault(key, {})[transform] = row
    return rows


def scan_slug(scan_set: str) -> str:
    return local_study.slugify(scan_set)


def patch_summary_by_level(result_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    by_level: dict[str, dict[str, dict[str, str]]] = {}
    for row in read_csv_rows(result_dir / "patch_summary.csv"):
        level = row.get("level", "")
        transform = row.get("transform", "")
        if level and transform:
            by_level.setdefault(level, {})[transform] = row
    return by_level


def metadata_diff_by_level(result_dir: Path) -> dict[str, dict[str, Any]]:
    by_level: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(result_dir / "metadata_diff_summary.csv"):
        level = row.get("level", "")
        if not level:
            continue
        item = by_level.setdefault(
            level,
            {
                "expected_encoder_change": 0,
                "review_preservation_change": 0,
                "review_preservation_fields": set(),
            },
        )
        changes = parse_int(row.get("changes")) or 0
        if row.get("interpretation") == "expected_encoder_change":
            item["expected_encoder_change"] += changes
        elif row.get("interpretation") == "review_preservation_change":
            item["review_preservation_change"] += changes
            item["review_preservation_fields"].update(
                field.strip()
                for field in row.get("fields", "").split(",")
                if field.strip()
            )
    return by_level


def channel_bias_max(row: dict[str, str]) -> float | None:
    values = [
        abs(value)
        for value in (
            parse_float(row.get("mean_bias_r_16bit")),
            parse_float(row.get("mean_bias_g_16bit")),
            parse_float(row.get("mean_bias_b_16bit")),
        )
        if value is not None
    ]
    return max(values) if values else None


def color_verdict(
    jxl_stress: float | None,
    raw_stress: float | None,
    metadata_risk: str,
) -> str:
    if jxl_stress is None:
        return "blocked_missing_jxl_color_metrics"
    if raw_stress is None:
        return "blocked_missing_raw61_color_metrics"
    if metadata_risk == "review_required":
        return "blocked_by_operational_risk"
    if jxl_stress < raw_stress * 0.8:
        return "ps16_jxl_wins"
    if jxl_stress <= raw_stress * 1.1:
        return "uncertain"
    return "raw61_likely_wins"


def metadata_risk(changes: int | None) -> str:
    if changes is None:
        return "blocked_missing_metadata_diff"
    if changes > 0:
        return "review_required"
    return "pass"


def size_brackets(rows: list[budget_index.BudgetRow]) -> dict[tuple[str, str], dict[str, str]]:
    grouped: dict[tuple[str, str], list[budget_index.BudgetRow]] = {}
    for row in rows:
        grouped.setdefault((row.scan_set, row.set_id), []).append(row)
    brackets: dict[tuple[str, str], dict[str, str]] = {}
    for key, items in grouped.items():
        valid = [row for row in items if row.candidate_vs_single_raw_pct is not None]
        below = [
            row
            for row in valid
            if row.candidate_vs_single_raw_pct is not None
            and row.candidate_vs_single_raw_pct <= 100
        ]
        above = [
            row
            for row in valid
            if row.candidate_vs_single_raw_pct is not None
            and row.candidate_vs_single_raw_pct >= 100
        ]
        nearest_below = max(
            below,
            key=lambda row: row.candidate_vs_single_raw_pct or -math.inf,
            default=None,
        )
        nearest_above = min(
            above,
            key=lambda row: row.candidate_vs_single_raw_pct or math.inf,
            default=None,
        )
        brackets[key] = {
            "nearest_below": nearest_below.level if nearest_below else "",
            "nearest_above": nearest_above.level if nearest_above else "",
        }
    return brackets


def evidence_status(
    raw_loss: RawLossRow | None,
    structure: StructureRow | None,
    color_result: str,
    metadata_result: str,
    size_status: str,
) -> str:
    missing: list[str] = []
    if size_status == "incomplete":
        missing.append("inputs")
    if raw_loss is None:
        missing.append("raw61_loss_metrics")
    if structure is None:
        missing.append("structure_metrics")
    elif structure.structure_verdict.startswith("blocked"):
        missing.append("structure_metrics")
    if color_result.startswith("blocked_missing"):
        missing.append("color_metrics")
    if metadata_result.startswith("blocked"):
        missing.append("metadata_diff")
    if missing:
        return "blocked_missing_" + "+".join(sorted(set(missing)))
    if metadata_result == "review_required":
        return "blocked_operational_review"
    return "complete"


def final_verdict(
    status: str,
    color_result: str,
    structure_result: str,
    metadata_result: str,
    size_status: str,
) -> str:
    if status != "complete":
        return status
    if metadata_result == "review_required":
        return "blocked_by_operational_risk"
    if size_status == "over_budget":
        return "uncertain_over_budget"
    if "raw61" in color_result or "raw61" in structure_result:
        return "raw61_likely_wins"
    if color_result.startswith("ps16_jxl") and structure_result.startswith("ps16_jxl"):
        return "ps16_jxl_likely_wins"
    return "uncertain"


def build_rows(
    budget_rows: list[budget_index.BudgetRow],
    verification_root: Path,
    raw_loss_rows: dict[tuple[str, str], RawLossRow],
    structure_rows: dict[tuple[str, str, str], StructureRow],
    rendered_jxl_sizes: dict[tuple[str, str, str], float] | None = None,
    rendered_patch_rows: dict[tuple[str, str, str], dict[str, dict[str, str]]] | None = None,
) -> list[BreakEvenRow]:
    rendered_jxl_sizes = rendered_jxl_sizes or {}
    rendered_patch_rows = rendered_patch_rows or {}
    brackets = size_brackets(budget_rows)
    patch_cache: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    metadata_cache: dict[str, dict[str, dict[str, Any]]] = {}
    rows: list[BreakEvenRow] = []
    for budget in budget_rows:
        rendered_key = (budget.scan_set, budget.set_id, budget.level)
        using_rendered_jxl = (
            rendered_key in rendered_jxl_sizes or rendered_key in rendered_patch_rows
        )
        result_dir = verification_root / f"{scan_slug(budget.scan_set)}_colorpatch"
        cache_key = str(result_dir)
        if cache_key not in patch_cache:
            patch_cache[cache_key] = patch_summary_by_level(result_dir)
            metadata_cache[cache_key] = metadata_diff_by_level(result_dir)
        patch_by_level = patch_cache[cache_key]
        metadata_by_level = metadata_cache[cache_key]
        if using_rendered_jxl:
            rendered_by_transform = rendered_patch_rows.get(rendered_key, {})
            identity = rendered_by_transform.get("identity", {})
            stress = rendered_by_transform.get(HARD_TRANSFORM, {})
        else:
            identity = patch_by_level.get(budget.level, {}).get("identity", {})
            stress = patch_by_level.get(budget.level, {}).get(HARD_TRANSFORM, {})
        diff = metadata_by_level.get(budget.level, {})
        if using_rendered_jxl:
            review_changes = 0
            fields = "-"
            meta_risk = "pass"
        else:
            review_changes = diff.get("review_preservation_change")
            fields = ", ".join(sorted(diff.get("review_preservation_fields", set()))) or "-"
            meta_risk = metadata_risk(review_changes)
        raw_loss = raw_loss_rows.get((budget.scan_set, budget.set_id))
        structure = structure_rows.get((budget.scan_set, budget.set_id, budget.level))
        jxl_stress = parse_float(stress.get("p95_delta_e00"))
        raw_stress = raw_loss.raw61_color_delta_e00_p95_stress if raw_loss else None
        c_verdict = color_verdict(jxl_stress, raw_stress, meta_risk)
        s_verdict = structure.structure_verdict if structure else "blocked_missing_structure_metrics"
        retained_size = rendered_jxl_sizes.get(rendered_key, budget.candidate_mib)
        size_vs_raw61 = budget_index.pct(retained_size, budget.single_raw_mib)
        if using_rendered_jxl:
            size_status, size_note = budget_index.row_status(
                budget.single_raw_mib,
                budget.pixelshift16_mib,
                retained_size,
                budget.level,
            )
        else:
            size_status, size_note = budget.status, budget.notes
        status = evidence_status(raw_loss, structure, c_verdict, meta_risk, size_status)
        verdict = final_verdict(status, c_verdict, s_verdict, meta_risk, size_status)
        bracket = brackets.get((budget.scan_set, budget.set_id), {})
        bracket_text = (
            f"below={bracket.get('nearest_below') or '-'}; "
            f"above={bracket.get('nearest_above') or '-'}"
        )
        notes = "; ".join(
            item
            for item in [
                size_note,
                "standalone rendered JXL candidate" if using_rendered_jxl else "",
                raw_loss.notes if raw_loss else "missing RAW61-vs-R16 metrics",
                structure.notes if structure else "missing structure/visual/target metrics",
            ]
            if item
        )
        rows.append(
            BreakEvenRow(
                scan_set=budget.scan_set,
                film_stock=budget.film_stock,
                film_type=budget.film_type,
                shot_year=budget.shot_year,
                set_id=budget.set_id,
                level=budget.level,
                retained_size_mib=retained_size,
                raw61_size_mib=budget.single_raw_mib,
                size_vs_raw61_pct=size_vs_raw61,
                size_status=size_status,
                size_bracket=bracket_text,
                color_delta_e00_p95_identity=parse_float(identity.get("p95_delta_e00")),
                color_delta_e00_p95_stress=jxl_stress,
                channel_bias_max_stress=channel_bias_max(stress),
                raw61_color_delta_e00_p95_identity=raw_loss.raw61_color_delta_e00_p95_identity
                if raw_loss
                else None,
                raw61_color_delta_e00_p95_stress=raw_stress,
                color_verdict=c_verdict,
                raw61_structure_loss=structure.raw61_structure_loss
                if structure
                else (raw_loss.raw61_structure_loss if raw_loss else None),
                jxl_structure_loss=structure.jxl_structure_loss if structure else None,
                structure_verdict=s_verdict,
                artifact_risk=structure.artifact_risk if structure else "unknown",
                metadata_review_changes=review_changes,
                metadata_review_fields=fields,
                metadata_risk=meta_risk,
                evidence_status=status,
                verdict=verdict,
                notes=notes,
            )
        )
    return rows


def write_csv(rows: list[BreakEvenRow], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(asdict(rows[0]).keys()) if rows else [field.name for field in BreakEvenRow.__dataclass_fields__.values()]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(rows: list[BreakEvenRow], target: Path) -> None:
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": [asdict(row) for row in rows],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_markdown(rows: list[BreakEvenRow], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Archival Break-Even Matrix",
        "",
        "Generated local output. This file is ignored by Git and may mention private scan folders.",
        "",
        f"Generated at UTC: `{generated_at}`",
        "",
        "This matrix follows `ARCHIVAL_VALUE_METRICS.md`. It is intentionally",
        "conservative: if RAW61 color/structure evidence is missing, verdicts are",
        "blocked instead of inferred from JPEG XL metrics alone.",
        "",
        "## Rows",
        "",
        "| Scan set | Set | Level | Size vs RAW61 | Size status | JXL stress p95 DeltaE00 | RAW61 stress p95 DeltaE00 | Color verdict | Structure verdict | Metadata risk | Evidence status | Verdict |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.scan_set}` | `{row.set_id}` | `{row.level}` | "
            f"{fmt(row.size_vs_raw61_pct, 1)}% | `{row.size_status}` | "
            f"{fmt(row.color_delta_e00_p95_stress)} | "
            f"{fmt(row.raw61_color_delta_e00_p95_stress)} | "
            f"`{row.color_verdict}` | `{row.structure_verdict}` | "
            f"`{row.metadata_risk}` | `{row.evidence_status}` | `{row.verdict}` |"
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    lines.extend(["", "## Verdict Counts", ""])
    for verdict, count in sorted(counts.items()):
        lines.append(f"- `{verdict}`: {count}")
    lines.extend(
        [
            "",
            "## Required External Evidence",
            "",
            "- RAW61-vs-R16 color/tone metrics for each capture set.",
            "- Registered structure/detail metrics or controlled visual verdicts.",
            "- Target/SFR measurements when suitable target captures exist.",
            "- Operational review for candidates with metadata review changes.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_templates(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_template = output_dir / "raw61_loss_template.csv"
    structure_template = output_dir / "structure_metrics_template.csv"
    raw_template.write_text(
        "\n".join(
            [
                "scan_set,set_id,raw61_color_delta_e00_p95_identity,raw61_color_delta_e00_p95_stress,raw61_channel_bias_max_stress,raw61_clipping_delta_stress,raw61_structure_loss,notes",
                "Example Film,frame001,0.25,0.80,120,0,0.45,replace this row",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    structure_template.write_text(
        "\n".join(
            [
                "scan_set,set_id,level,scope,raw61_structure_loss,jxl_structure_loss,artifact_risk,structure_verdict,notes",
                "Example Film,frame001,d005,native-detail,0.45,0.30,low,ps16_jxl_likely_wins,replace this row",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a conservative archival break-even matrix from local scan manifests, "
            "DNG/JXL verification results, and optional RAW61/structure metrics."
        )
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--verification-root", type=Path, default=DEFAULT_VERIFICATION_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-loss-csv", type=Path)
    parser.add_argument("--structure-csv", type=Path)
    parser.add_argument(
        "--rendered-jxl-matrix-csv",
        type=Path,
        help="Standalone rendered-PS16 JXL matrix CSV; overrides ADC candidate sizes when present.",
    )
    parser.add_argument(
        "--rendered-jxl-patch-summary-csv",
        type=Path,
        help="Standalone rendered-PS16 JXL patch summary grouped by scan_set,set_id,level,transform.",
    )
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument(
        "--write-templates",
        action="store_true",
        help="Write CSV templates for RAW61 and structure metrics into the output directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.write_templates:
        write_templates(args.output_dir)
    roots = budget_index.discover_scan_roots(args.input_root, args.scan_root)
    budget_rows: list[budget_index.BudgetRow] = []
    for root in roots:
        budget_rows.extend(budget_index.collect_rows(root, levels))
    rows = build_rows(
        budget_rows=budget_rows,
        verification_root=args.verification_root,
        raw_loss_rows=load_raw_loss(args.raw_loss_csv),
        structure_rows=load_structure(args.structure_csv),
        rendered_jxl_sizes=load_rendered_jxl_sizes(args.rendered_jxl_matrix_csv),
        rendered_patch_rows=load_rendered_patch_summary(args.rendered_jxl_patch_summary_csv),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.output_dir / "archival_break_even_matrix.csv")
    write_json(rows, args.output_dir / "archival_break_even_matrix.json")
    write_markdown(rows, args.output_dir / "ARCHIVAL_BREAK_EVEN_MATRIX.md")
    print(f"Wrote {len(rows)} row(s) to {relpath(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
