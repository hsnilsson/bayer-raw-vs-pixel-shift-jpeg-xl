from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jxl_levels import DEFAULT_LEVELS, require_level


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "input"
DEFAULT_OUTPUT_DIR = ROOT / "results/storage_budget_index"


@dataclass
class BudgetRow:
    scan_set: str
    film_stock: str
    film_type: str
    shot_year: str
    set_id: str
    single_raw: str
    pixelshift4_dng: str
    pixelshift16_dng: str
    level: str
    single_raw_mib: float | None
    pixelshift4_mib: float | None
    pixelshift16_mib: float | None
    candidate_mib: float | None
    candidate_vs_single_raw_pct: float | None
    candidate_vs_pixelshift16_pct: float | None
    storage_budget_role: str
    status: str
    notes: str


def relpath(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def mib(path: Path | None) -> float | None:
    if path is None or not path.is_file():
        return None
    return path.stat().st_size / 1024 / 1024


def pct(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole == 0:
        return None
    return part / whole * 100


def fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def load_manifest(scan_root: Path) -> dict[str, Any] | None:
    path = scan_root / "scan_manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def discover_scan_roots(input_root: Path, explicit_roots: list[Path] | None) -> list[Path]:
    if explicit_roots:
        return [path.resolve() for path in explicit_roots]
    if not input_root.is_dir():
        return []
    return [
        path.resolve()
        for path in sorted(input_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and not path.name.startswith("_")
    ]


def row_status(
    single_size: float | None,
    ps16_size: float | None,
    candidate_size: float | None,
    level: str,
) -> tuple[str, str]:
    notes: list[str] = []
    if single_size is None:
        notes.append("missing single-shot raw")
    if ps16_size is None:
        notes.append("missing PixelShift 16 DNG")
    if candidate_size is None:
        notes.append(f"missing ADC {level} candidate")
    if notes:
        return "incomplete", "; ".join(notes)
    assert single_size is not None
    assert candidate_size is not None
    ratio = candidate_size / single_size
    if 0.95 <= ratio <= 1.05:
        return "within_5pct_budget", "candidate size is within +/-5% of single-shot raw"
    if ratio < 0.95:
        return "under_budget", "candidate is smaller than single-shot raw budget"
    return "over_budget", "candidate is larger than single-shot raw budget"


def collect_rows(scan_root: Path, levels: list[str]) -> list[BudgetRow]:
    manifest = load_manifest(scan_root)
    if not manifest:
        return []
    rows: list[BudgetRow] = []
    scan_set = manifest.get("scan_root_name") or scan_root.name
    for capture in manifest.get("capture_sets", []):
        single = capture.get("single_raw")
        ps4 = capture.get("pixelshift4_dng")
        ps16 = capture.get("pixelshift16_dng")
        single_size = mib(scan_root / single) if single else None
        ps4_size = mib(scan_root / ps4) if ps4 else None
        ps16_size = mib(scan_root / ps16) if ps16 else None
        for level in levels:
            candidate = scan_root / "adc_jxl_dng" / level / Path(ps16).name if ps16 else None
            candidate_size = mib(candidate)
            status, notes = row_status(single_size, ps16_size, candidate_size, level)
            rows.append(
                BudgetRow(
                    scan_set=scan_set,
                    film_stock=manifest.get("film_stock", ""),
                    film_type=manifest.get("film_type", ""),
                    shot_year=str(manifest.get("shot_year", "")),
                    set_id=capture.get("set_id", ""),
                    single_raw=single or "",
                    pixelshift4_dng=ps4 or "",
                    pixelshift16_dng=ps16 or "",
                    level=level,
                    single_raw_mib=single_size,
                    pixelshift4_mib=ps4_size,
                    pixelshift16_mib=ps16_size,
                    candidate_mib=candidate_size,
                    candidate_vs_single_raw_pct=pct(candidate_size, single_size),
                    candidate_vs_pixelshift16_pct=pct(candidate_size, ps16_size),
                    storage_budget_role=capture.get("storage_budget_role", ""),
                    status=status,
                    notes=notes,
                )
            )
    return rows


def write_csv(rows: list[BudgetRow], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()) if rows else [])
        if rows:
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))


def write_json(rows: list[BudgetRow], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": [asdict(row) for row in rows],
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(rows: list[BudgetRow], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Storage Budget Index",
        "",
        "Generated local output. This file is ignored by Git and may mention private scan folders.",
        "",
        f"Generated at UTC: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "This index answers a narrow question: which current local capture sets have",
        "a single-shot raw baseline, a PixelShift 16 DNG, and ADC JXL DNG candidates",
        "that can be compared by retained master size. It does not measure image",
        "quality or prove that a candidate is archival.",
        "",
        "## Rows",
        "",
        "| Scan set | Set | Level | Single raw MiB | PS4 DNG MiB | PS16 DNG MiB | Candidate MiB | Candidate vs raw | Candidate vs PS16 | Status | Notes |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"`{row.scan_set}` | `{row.set_id}` | `{row.level}` | "
            f"{fmt(row.single_raw_mib)} | {fmt(row.pixelshift4_mib)} | "
            f"{fmt(row.pixelshift16_mib)} | {fmt(row.candidate_mib)} | "
            f"{fmt(row.candidate_vs_single_raw_pct)}% | "
            f"{fmt(row.candidate_vs_pixelshift16_pct)}% | "
            f"`{row.status}` | {row.notes or '-'} |"
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    lines.extend(["", "## Status Counts", ""])
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: {count}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scan-root", type=Path, action="append", default=None)
    parser.add_argument("--level", action="append", default=None)
    args = parser.parse_args()

    try:
        levels = [require_level(level) for level in (args.level or DEFAULT_LEVELS)]
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    rows: list[BudgetRow] = []
    for scan_root in discover_scan_roots(args.input_root, args.scan_root):
        rows.extend(collect_rows(scan_root, levels))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(rows, args.output_dir / "storage_budget_index.json")
    write_markdown(rows, args.output_dir / "STORAGE_BUDGET_INDEX.md")
    if rows:
        write_csv(rows, args.output_dir / "storage_budget_index.csv")

    print(f"Wrote {len(rows)} row(s) to {relpath(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
