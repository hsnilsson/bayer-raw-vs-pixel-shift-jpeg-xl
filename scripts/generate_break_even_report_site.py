from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))
import run_local_scan_study as local_study  # noqa: E402


DEFAULT_MATRIX = ROOT / "results/archival_break_even/archival_break_even_matrix.csv"
DEFAULT_PANELS = ROOT / "results/break_even_review_panels"
DEFAULT_CONTEXTS = ROOT / "results/break_even_review_contexts"
DEFAULT_OUTPUT = ROOT / "results/break_even_report/index.html"
DEFAULT_PROFILE = ROOT / "profiles/rawtherapee/neutral-render.pp3"
DEFAULT_RENDER_INDEX = ROOT / "outputs/rawtherapee_renders/rawtherapee_render_index.csv"
DEFAULT_EXCLUDE_CASES = ROOT / "site/publication_exclude_cases.txt"
DEFAULT_VIEWERS = ROOT / "site/assets/review-viewers"
DEFAULT_ANNOTATIONS = ROOT / "metadata/scan_annotations.json"
DEFAULT_PUBLIC_FIGURES = ROOT / "docs/figures/public-latitude-v2"
VISUAL_STRESS_LEVELS = {"d100", "d150", "d200"}

PUBLIC_LATITUDE_CAPTIONS = {
    "fadgi-negative35mm2-d005-density-hard-print.png": "FADGI Negative 35mm 2, JXL d=0.05, hard density-inversion stress",
    "fadgi-negative35mm2-d010-density-hard-print.png": "FADGI Negative 35mm 2, JXL d=0.10, hard density-inversion stress",
    "loc-golden-gate-d005-density-hard-print.png": "LOC Golden Gate, JXL d=0.05, hard density-inversion stress",
    "loc-golden-gate-d010-density-hard-print.png": "LOC Golden Gate, JXL d=0.10, hard density-inversion stress",
    "loc-wildflowers-d005-density-hard-print.png": "LOC wildflowers, JXL d=0.05, hard density-inversion stress",
    "loc-wildflowers-d010-density-hard-print.png": "LOC wildflowers, JXL d=0.10, hard density-inversion stress",
}


@dataclass(frozen=True)
class LevelSummary:
    level: str
    rows: int
    median_retained_mib: float | None
    min_retained_mib: float | None
    max_retained_mib: float | None
    median_raw61_mib: float | None
    median_size_pct: float | None
    min_size_pct: float | None
    max_size_pct: float | None
    median_jxl_delta_e: float | None
    p95_jxl_delta_e: float | None
    median_raw_delta_e: float | None
    median_color_ratio: float | None
    median_jxl_structure_loss: float | None
    median_raw_structure_loss: float | None
    median_structure_ratio: float | None
    verdicts: Counter[str]
    status: str


@dataclass(frozen=True)
class BaselineSummary:
    scan_set: str
    set_id: str
    raw_delta_e_identity: float | None
    raw_delta_e_stress: float | None
    raw_structure_loss: float | None
    worst_jxl_delta_e_stress: float | None
    worst_jxl_structure_loss: float | None
    notes: str


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_exclude_cases(path: Path | None, explicit: list[str] | None = None) -> set[tuple[str, str]]:
    cases: set[tuple[str, str]] = set()
    values = list(explicit or [])
    if path and path.is_file():
        values.extend(path.read_text(encoding="utf-8").splitlines())
    for value in values:
        text = value.strip()
        if not text or text.startswith("#"):
            continue
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f'exclude case must be "scan_set_or_slug|set_id": {value!r}')
        cases.add((parts[0], parts[1]))
    return cases


def read_annotations(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    annotations: dict[tuple[str, str], dict[str, str]] = {}
    for key, value in payload.items():
        parts = [part.strip() for part in key.split("|", 1)]
        if len(parts) == 2 and isinstance(value, dict):
            item = {str(name): str(item) for name, item in value.items()}
            annotations[(parts[0], parts[1])] = item
            annotations[(local_study.slugify(parts[0]), parts[1])] = item
    return annotations


def annotation_for(scan_set_or_slug: str, set_id: str, annotations: dict[tuple[str, str], dict[str, str]]) -> dict[str, str]:
    slug = local_study.slugify(scan_set_or_slug)
    return annotations.get((scan_set_or_slug, set_id), annotations.get((slug, set_id), {}))


def case_is_excluded(scan_set_or_slug: str, set_id: str, excludes: set[tuple[str, str]]) -> bool:
    if not excludes:
        return False
    slug = scan_set_or_slug.lower()
    try:
        slug = local_study.slugify(scan_set_or_slug)
    except Exception:
        pass
    return (scan_set_or_slug, set_id) in excludes or (slug, set_id) in excludes


def filter_rows(rows: list[dict[str, str]], excludes: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if not case_is_excluded(row.get("scan_set", ""), row.get("set_id", ""), excludes)
    ]


def filter_case_paths(paths: list[Path], excludes: set[tuple[str, str]]) -> list[Path]:
    filtered: list[Path] = []
    for path in paths:
        if path.name == "index.html":
            metadata = read_viewer_metadata(path)
            scan_set = str(metadata.get("scan_set", ""))
            set_id = str(metadata.get("set_id", ""))
            if scan_set and set_id and case_is_excluded(scan_set, set_id, excludes):
                continue
        if len(path.parts) >= 3 and case_is_excluded(path.parent.parent.name, path.parent.name, excludes):
            continue
        if len(path.parts) >= 4 and case_is_excluded(path.parent.parent.parent.name, path.parent.parent.name, excludes):
            continue
        filtered.append(path)
    return filtered


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def median(values: Iterable[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return statistics.median(cleaned) if cleaned else None


def max_value(values: Iterable[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return max(cleaned) if cleaned else None


def min_value(values: Iterable[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return min(cleaned) if cleaned else None


def fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}{suffix}"


def fmt_with_unit(value: float | None, digits: int, unit: str) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f} {unit}"


def fmt_delta_e(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f} &Delta;E00"


def fmt_raw61_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}x RAW61"


def level_sort(level: str) -> tuple[int, str]:
    digits = "".join(char for char in level if char.isdigit())
    return (int(digits) if digits else 9999, level)


def classify_size(median_size_pct: float | None) -> str:
    if median_size_pct is None:
        return "unknown"
    if median_size_pct <= 100:
        return "good"
    if median_size_pct <= 115:
        return "warn"
    return "bad"


def classify_delta_e(delta_e: float | None) -> str:
    if delta_e is None:
        return "unknown"
    if delta_e <= 1.0:
        return "good"
    if delta_e <= 2.0:
        return "warn"
    if delta_e <= 3.0:
        return "risk"
    return "bad"


def classify_ratio(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 0.50:
        return "good"
    if value <= 0.80:
        return "warn"
    if value <= 1.10:
        return "risk"
    return "bad"


def classify_verdict(verdicts: Counter[str]) -> str:
    if verdicts.get("raw61_likely_wins", 0):
        return "bad"
    if verdicts.get("uncertain", 0) or verdicts.get("uncertain_over_budget", 0):
        return "warn"
    if verdicts.get("ps16_jxl_likely_wins", 0):
        return "good"
    return "unknown"


def status_for(summary: LevelSummary) -> str:
    if summary.level in VISUAL_STRESS_LEVELS:
        return "Visual stress only"
    size = classify_size(summary.median_size_pct)
    color = classify_delta_e(summary.p95_jxl_delta_e)
    color_ratio = classify_ratio(summary.median_color_ratio)
    structure_ratio = classify_ratio(summary.median_structure_ratio)
    verdict = classify_verdict(summary.verdicts)
    if size == "bad":
        return "Too large"
    if verdict == "bad" or color == "bad":
        return "Image risk"
    if size == "good" and verdict == "good" and color in {"good", "warn"} and "bad" not in {color_ratio, structure_ratio}:
        return "Passes current gates"
    if "risk" in {color, color_ratio, structure_ratio} or "warn" in {size, color, color_ratio, structure_ratio, verdict}:
        return "Review zone"
    return "Incomplete"


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def summarize_levels(rows: list[dict[str, str]]) -> list[LevelSummary]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("evidence_status") == "complete":
            grouped[row.get("level", "")].append(row)
    summaries: list[LevelSummary] = []
    for level, items in grouped.items():
        verdicts = Counter(row.get("verdict", "") for row in items)
        jxl_delta_values = [parse_float(row.get("color_delta_e00_p95_stress")) for row in items]
        raw_delta_values = [parse_float(row.get("raw61_color_delta_e00_p95_stress")) for row in items]
        jxl_structure_values = [parse_float(row.get("jxl_structure_loss")) for row in items]
        raw_structure_values = [parse_float(row.get("raw61_structure_loss")) for row in items]
        summary = LevelSummary(
            level=level,
            rows=len(items),
            median_retained_mib=median(parse_float(row.get("retained_size_mib")) for row in items),
            min_retained_mib=min_value(parse_float(row.get("retained_size_mib")) for row in items),
            max_retained_mib=max_value(parse_float(row.get("retained_size_mib")) for row in items),
            median_raw61_mib=median(parse_float(row.get("raw61_size_mib")) for row in items),
            median_size_pct=median(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            min_size_pct=min_value(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            max_size_pct=max_value(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            median_jxl_delta_e=median(jxl_delta_values),
            p95_jxl_delta_e=percentile(jxl_delta_values, 95),
            median_raw_delta_e=median(raw_delta_values),
            median_color_ratio=median(
                ratio(parse_float(row.get("color_delta_e00_p95_stress")), parse_float(row.get("raw61_color_delta_e00_p95_stress")))
                for row in items
            ),
            median_jxl_structure_loss=median(jxl_structure_values),
            median_raw_structure_loss=median(raw_structure_values),
            median_structure_ratio=median(
                ratio(parse_float(row.get("jxl_structure_loss")), parse_float(row.get("raw61_structure_loss")))
                for row in items
            ),
            verdicts=verdicts,
            status="",
        )
        summaries.append(
            LevelSummary(
                **{**summary.__dict__, "status": status_for(summary)}
            )
        )
    return sorted(summaries, key=lambda item: level_sort(item.level))


def percentile(values: Iterable[float | None], pct: float) -> float | None:
    cleaned = sorted(value for value in values if value is not None)
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    position = (len(cleaned) - 1) * pct / 100.0
    lower = int(position)
    upper = min(lower + 1, len(cleaned) - 1)
    fraction = position - lower
    return cleaned[lower] * (1.0 - fraction) + cleaned[upper] * fraction


def summarize_baselines(rows: list[dict[str, str]]) -> list[BaselineSummary]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("evidence_status") == "complete":
            grouped[(row.get("scan_set", ""), row.get("set_id", ""))].append(row)
    summaries: list[BaselineSummary] = []
    for (scan_set, set_id), items in grouped.items():
        first = items[0]
        summaries.append(
            BaselineSummary(
                scan_set=scan_set,
                set_id=set_id,
                raw_delta_e_identity=parse_float(first.get("raw61_color_delta_e00_p95_identity")),
                raw_delta_e_stress=parse_float(first.get("raw61_color_delta_e00_p95_stress")),
                raw_structure_loss=parse_float(first.get("raw61_structure_loss")),
                worst_jxl_delta_e_stress=max_value(parse_float(row.get("color_delta_e00_p95_stress")) for row in items),
                worst_jxl_structure_loss=max_value(parse_float(row.get("jxl_structure_loss")) for row in items),
                notes=first.get("notes", ""),
            )
        )
    return sorted(summaries, key=lambda item: (item.scan_set.lower(), item.set_id.lower()))


def verdict_text(counter: Counter[str]) -> str:
    return ", ".join(f"{html.escape(key)}: {value}" for key, value in sorted(counter.items())) or "-"


def abbr(label: str, title: str) -> str:
    return f'<abbr title="{esc(title)}">{esc(label)}</abbr>'


def column_help(short: str, full: str) -> str:
    return f'<th><span class="column-help">{esc(full)}</span></th>'


def read_profile_flags(path: Path) -> dict[str, str]:
    flags = {
        "white_balance_enabled": "unknown",
        "white_balance_setting": "unknown",
        "input_profile": "unknown",
        "working_profile": "unknown",
        "output_profile": "unknown",
        "raw_bayer_method": "unknown",
        "sharpening_enabled": "unknown",
    }
    if not path.is_file():
        return flags
    section = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1]
            continue
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        if section == "White Balance" and key == "Enabled":
            flags["white_balance_enabled"] = value
        elif section == "White Balance" and key == "Setting":
            flags["white_balance_setting"] = value
        elif section == "Color Management" and key == "InputProfile":
            flags["input_profile"] = value
        elif section == "Color Management" and key == "WorkingProfile":
            flags["working_profile"] = value
        elif section == "Color Management" and key == "OutputProfile":
            flags["output_profile"] = value
        elif section == "RAW Bayer" and key == "Method":
            flags["raw_bayer_method"] = value
        elif section == "Sharpening" and key == "Enabled":
            flags["sharpening_enabled"] = value
    return flags


def render_pair_count(path: Path) -> tuple[int, int]:
    rows = read_rows(path)
    raw61 = sum(1 for row in rows if row.get("role") == "raw61")
    ps16 = sum(1 for row in rows if row.get("role") == "ps16")
    return raw61, ps16


def level_status_class(status: str) -> str:
    return {
        "Passes current gates": "good",
        "Review zone": "warn",
        "Too large": "bad",
        "Image risk": "bad",
        "Visual stress only": "unknown",
    }.get(status, "unknown")


def size_reading(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 100:
        return "within RAW61 budget"
    if value <= 115:
        return "near RAW61 budget"
    return "larger than RAW61"


def delta_e_reading(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0.25:
        return "very small codec color shift"
    if value <= 1.0:
        return "small codec color shift"
    if value <= 2.0:
        return "visible if inspected"
    if value <= 3.0:
        return "review carefully"
    return "large for this use"


def ratio_reading(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0.5:
        return "well below RAW61 baseline"
    if value <= 0.8:
        return "below RAW61 baseline"
    if value <= 1.1:
        return "near RAW61 baseline"
    return "worse than RAW61 baseline"


def structure_reading(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"error is {value * 100:.1f}% of PS16 high-frequency RMS"


def status_reading(status: str) -> str:
    return {
        "Too large": "image metrics may still be strong, but median size is above RAW61",
        "Review zone": "near the storage or image-quality boundary; needs visual review",
        "Passes current gates": "median size is under RAW61 and current diagnostics favor PS16 JXL",
        "Image risk": "one or more current image diagnostics fails conservative thresholds",
        "Visual stress only": "deliberately aggressive reference; excluded from archive-candidate verdicts",
    }.get(status, "incomplete evidence")


def lossless_reference_row() -> str:
    return (
        '<tr class="reference-row">'
        '<td><strong>lossless</strong></td>'
        '<td class="unknown">Reference only<br><span class="subtle">not counted as a break-even candidate</span></td>'
        '<td>not in current matrix<br><span class="subtle">complete standalone lossless sizes still need a separate run</span></td>'
        '<td>-<br><span class="subtle">shown to anchor the codec scale</span></td>'
        '<td>-</td>'
        '<td class="good"><strong>0.00 &Delta;E00</strong><br><span class="subtle">by definition against the PS16 reference</span></td>'
        '<td class="good"><strong>0.00x RAW61</strong><br><span class="subtle">zero codec color loss</span></td>'
        '<td><strong>0.000 loss</strong><br><span class="subtle">zero high-pass codec loss</span></td>'
        '<td class="good"><strong>0.00x RAW61</strong><br><span class="subtle">zero codec structure loss</span></td>'
        "<td>baseline; excluded from break-even counts</td>"
        "</tr>"
    )


def level_chart(summaries: list[LevelSummary]) -> str:
    """Compact categorical bars; JXL distances are sampled levels, not an even numeric axis."""
    items = [item for item in summaries if item.median_size_pct is not None]
    if not items:
        return ""
    charts = [
        ("Storage vs RAW61", "%", [item.median_size_pct for item in items], 100.0),
        ("Color loss vs RAW61", "x", [item.median_color_ratio for item in items], 1.0),
        ("Structure loss vs RAW61", "x", [item.median_structure_ratio for item in items], 1.0),
    ]
    rendered = []
    for title, unit, values, gate in charts:
        numeric = [float(value) for value in values if value is not None]
        if not numeric:
            continue
        maximum = max(max(numeric), gate) * 1.12
        bars = []
        labels = []
        slot_width = 252 / max(1, len(items))
        bar_width = min(18.0, slot_width * 0.62)
        for index, (item, value) in enumerate(zip(items, values)):
            if value is None:
                continue
            x = 34 + slot_width * (index + 0.5)
            y = 116 - float(value) / maximum * 86
            height = max(0.75, 116 - y)
            value_text = f"{float(value):.1f}{unit}" if unit == "%" else f"{float(value):.2f}{unit}"
            bar_class = "chart-bar chart-bar-pass" if float(value) <= gate else "chart-bar chart-bar-over"
            bars.append(
                f'<rect x="{x - bar_width / 2:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{height:.1f}" class="{bar_class}"><title>{esc(item.level)}: {esc(value_text)}</title></rect>'
            )
            labels.append(f'<text x="{x:.1f}" y="136" text-anchor="middle">{esc(item.level)}</text>')
        gate_y = 116 - gate / maximum * 86
        rendered.append(
            f'''<figure class="trend-chart"><figcaption><strong>{esc(title)}</strong><span>lower is better; dashed line = {gate:g}{esc(unit)} RAW61 gate</span></figcaption>
            <svg viewBox="0 0 320 150" role="img" aria-label="{esc(title)} by JPEG XL distance">
              <line x1="34" y1="116" x2="286" y2="116" class="chart-axis"/><line x1="34" y1="30" x2="34" y2="116" class="chart-axis"/>
              <line x1="34" y1="{gate_y:.1f}" x2="286" y2="{gate_y:.1f}" class="chart-gate"/>
              <text x="4" y="{gate_y + 4:.1f}">{gate:g}{esc(unit)}</text>
              {''.join(bars)}{''.join(labels)}
            </svg></figure>'''
        )
    return f'<section class="trend-charts" aria-label="Level trends">{"".join(rendered)}</section>'


def conclusion_text(summaries: list[LevelSummary]) -> str:
    first_under = next((item for item in summaries if item.median_size_pct is not None and item.median_size_pct <= 100), None)
    last_over = None
    if first_under is not None:
        for item in summaries:
            if item is first_under:
                break
            if item.median_size_pct is not None and item.median_size_pct > 100:
                last_over = item
    if first_under and last_over:
        return (
            f"The current local data puts the storage break-even between {esc(last_over.level)} "
            f"({fmt(last_over.median_size_pct, 1, '%')}) and {esc(first_under.level)} "
            f"({fmt(first_under.median_size_pct, 1, '%')})."
        )
    if first_under:
        return f"The first tested level within the RAW61 size budget is {esc(first_under.level)}."
    return "No tested level is within the RAW61 size budget yet."


def panel_paths(panel_root: Path, output: Path) -> list[Path]:
    if not panel_root.is_dir():
        return []
    panels = list(panel_root.rglob("*.png"))
    panels.sort(key=lambda path: (path.parent.as_posix(), level_sort(path.name), path.name))
    return panels


def panel_groups(panels: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in panels:
        parent = path.parent
        label = "/".join(parent.parts[-2:]) if len(parent.parts) >= 2 else parent.name
        groups[label].append(path)
    return dict(sorted(groups.items()))


def context_paths(context_root: Path) -> list[Path]:
    if not context_root.is_dir():
        return []
    contexts = [path for path in context_root.rglob("*.png")]
    contexts.sort(key=lambda path: (path.parent.as_posix(), path.name))
    return contexts


def context_groups(contexts: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in contexts:
        parent = path.parent
        label = "/".join(parent.parts[-2:]) if len(parent.parts) >= 2 else parent.name
        groups[label].append(path)
    return dict(sorted(groups.items()))


def viewer_paths(viewer_root: Path) -> list[Path]:
    if not viewer_root.is_dir():
        return []
    paths = [path for path in viewer_root.rglob("index.html")]
    nested_cases: set[tuple[str, str]] = set()
    for path in paths:
        try:
            relative = path.relative_to(viewer_root)
        except ValueError:
            continue
        if len(relative.parts) >= 4:
            nested_cases.add((relative.parts[0], relative.parts[1]))
    filtered = []
    for path in paths:
        try:
            relative = path.relative_to(viewer_root)
        except ValueError:
            filtered.append(path)
            continue
        if len(relative.parts) == 3 and (relative.parts[0], relative.parts[1]) in nested_cases:
            continue
        filtered.append(path)
    paths = filtered
    paths.sort(key=lambda path: path.parent.as_posix())
    return paths


def read_viewer_metadata(index_path: Path) -> dict[str, object]:
    metadata_path = index_path.parent / "metadata.json"
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    except json.JSONDecodeError:
        return {}


def viewer_group_name(index_path: Path) -> str:
    metadata = read_viewer_metadata(index_path)
    scan_set = str(metadata.get("scan_set") or "")
    set_id = str(metadata.get("set_id") or "")
    if scan_set and set_id:
        return f"{local_study.slugify(scan_set)}/{set_id}"
    parent = index_path.parent
    if len(parent.parts) >= 3:
        return "/".join(parent.parts[-3:-1]) if parent.name.startswith("manual-") else "/".join(parent.parts[-2:])
    return parent.name


def viewer_groups(viewers: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in viewers:
        groups[viewer_group_name(path)].append(path)
    return dict(sorted(groups.items()))


def viewer_level_key(path: Path | str) -> tuple[int, str]:
    name = path.stem if isinstance(path, Path) else str(path)
    if name.startswith("jxl_"):
        return level_sort(name.removeprefix("jxl_"))
    return (9999, name)


def viewer_display_label(scan_set_or_slug: str, set_id: str, annotations: dict[tuple[str, str], dict[str, str]]) -> str:
    annotation = annotation_for(scan_set_or_slug, set_id, annotations)
    if annotation.get("material_label"):
        return f'{annotation["material_label"]} / {set_id}'
    return f"{scan_set_or_slug} / {set_id}"


def viewer_records(
    viewers: list[Path],
    output: Path,
    annotations: dict[tuple[str, str], dict[str, str]],
    rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    size_lookup: dict[tuple[str, str, str], float] = {}
    for row in rows or []:
        scan_slug = local_study.slugify(row.get("scan_set", ""))
        set_id = row.get("set_id", "")
        level = row.get("level", "")
        raw_size = parse_float(row.get("raw61_size_mib"))
        retained_size = parse_float(row.get("retained_size_mib"))
        if raw_size is not None:
            size_lookup[(scan_slug, set_id, "raw61")] = raw_size
        if retained_size is not None and level:
            size_lookup[(scan_slug, set_id, level)] = retained_size
    records: list[dict[str, object]] = []
    index_by_path: dict[str, int] = {}
    for index_path in viewers:
        directory = index_path.parent
        metadata = read_viewer_metadata(index_path)
        labels = metadata.get("labels", {}) if isinstance(metadata.get("labels", {}), dict) else {}
        overviews = metadata.get("overviews", {}) if isinstance(metadata.get("overviews", {}), dict) else {}
        image_sets = metadata.get("images_by_transform", {}) if isinstance(metadata.get("images_by_transform", {}), dict) else {}
        mode_items = metadata.get("view_modes", []) if isinstance(metadata.get("view_modes", []), list) else []
        view_modes = [item for item in mode_items if isinstance(item, dict) and item.get("key") in image_sets]
        if not view_modes:
            legacy_key = str(metadata.get("transform") or "identity")
            image_sets = {legacy_key: {"reference": "reference.png", "raw61": "raw61.png"}}
            for path in directory.glob("jxl_*.png"):
                image_sets[legacy_key][path.stem] = path.name
            view_modes = [{"key": legacy_key, "label": "Normal", "description": "Unmodified display of the rendered crop."}]
        default_mode = str(metadata.get("default_transform") or view_modes[0].get("key"))
        if default_mode not in image_sets:
            default_mode = str(view_modes[0].get("key"))
        scan_set = str(metadata.get("scan_set") or directory.parent.name)
        set_id = str(metadata.get("set_id") or directory.name)
        scan_slug = local_study.slugify(scan_set)
        crop_name = str(metadata.get("crop_name") or "")
        candidates: list[dict[str, object]] = []
        reference_sources = {
            str(mode.get("key")): relpath(directory / str(image_sets[str(mode.get("key"))].get("reference", "")), output)
            for mode in view_modes
            if (directory / str(image_sets[str(mode.get("key"))].get("reference", ""))).is_file()
        }
        reference_path = directory / str(image_sets[default_mode].get("reference", ""))
        reference_overview_path = directory / str(overviews.get("reference", ""))
        if reference_path.is_file():
            candidates.append(
                {
                    "key": "ps16_lossless",
                    "label": "PS16 lossless / reference",
                    "src": reference_sources.get(default_mode, relpath(reference_path, output)),
                    "sources": reference_sources,
                    "role": "baseline",
                    "overview": relpath(reference_overview_path, output) if reference_overview_path.is_file() else "",
                }
            )
        raw_sources = {
            str(mode.get("key")): relpath(directory / str(image_sets[str(mode.get("key"))].get("raw61", "")), output)
            for mode in view_modes
            if (directory / str(image_sets[str(mode.get("key"))].get("raw61", ""))).is_file()
        }
        raw61_path = directory / str(image_sets[default_mode].get("raw61", ""))
        raw61_overview_path = directory / str(overviews.get("raw61", ""))
        if raw61_path.is_file():
            candidates.append(
                {
                    "key": "raw61",
                    "label": str(labels.get("raw61", "RAW61 local aligned")),
                    "src": raw_sources.get(default_mode, relpath(raw61_path, output)),
                    "sources": raw_sources,
                    "role": "raw61",
                    "storageMib": size_lookup.get((scan_slug, set_id, "raw61")),
                    "storageKind": "source ARW",
                    "overview": relpath(raw61_overview_path, output) if raw61_overview_path.is_file() else "",
                }
            )
        keys = sorted(
            {key for image_set in image_sets.values() if isinstance(image_set, dict) for key in image_set if key.startswith("jxl_")},
            key=viewer_level_key,
        )
        for key in keys:
            sources = {
                str(mode.get("key")): relpath(directory / str(image_sets[str(mode.get("key"))].get(key, "")), output)
                for mode in view_modes
                if (directory / str(image_sets[str(mode.get("key"))].get(key, ""))).is_file()
            }
            if default_mode not in sources:
                continue
            label = str(labels.get(key, key.replace("_", " ").upper()))
            if key in {"jxl_d100", "jxl_d150", "jxl_d200"}:
                label = f"{label} (hard visual check)"
            candidates.append(
                {
                    "key": key,
                    "label": label,
                    "src": sources[default_mode],
                    "sources": sources,
                    "role": "jxl",
                    "storageMib": size_lookup.get((scan_slug, set_id, key.removeprefix("jxl_"))),
                    "storageKind": "encoded JXL",
                    "overview": (
                        relpath(directory / str(overviews.get(key, "")), output)
                        if (directory / str(overviews.get(key, ""))).is_file()
                        else ""
                    ),
                }
            )
        if not reference_path.is_file() or not candidates:
            continue
        annotation = annotation_for(scan_set, set_id, annotations)
        label = viewer_display_label(scan_set, set_id, annotations)
        if crop_name:
            label = f"{label} / {crop_name}"
        index_by_path[str(index_path.resolve())] = len(records)
        records.append(
            {
                "index": len(records),
                "group": viewer_group_name(index_path),
                "label": label,
                "material": annotation.get("material_label", scan_set),
                "sampleRole": annotation.get("sample_role", ""),
                "setId": set_id,
                "scanSet": scan_set,
                "reference": reference_sources.get(default_mode, relpath(reference_path, output)),
                "references": reference_sources,
                "referenceOverview": relpath(reference_overview_path, output) if reference_overview_path.is_file() else "",
                "candidates": candidates,
                "metadata": {
                    "transform": default_mode,
                    "defaultTransform": default_mode,
                    "viewModes": view_modes,
                    "cropName": crop_name,
                    "crop": metadata.get("crop", []),
                    "localRaw61Alignment": metadata.get("local_raw61_alignment", {}),
                },
            }
        )
    return records, index_by_path


def copy_panel_assets(panels: list[Path], panel_root: Path, target_root: Path) -> list[Path]:
    copied: list[Path] = []
    for path in panels:
        try:
            relative = path.resolve().relative_to(panel_root.resolve())
        except ValueError:
            relative = Path(path.name)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        copied.append(target)
    return copied


def copy_context_assets(contexts: list[Path], context_root: Path, target_root: Path) -> list[Path]:
    copied: list[Path] = []
    for path in contexts:
        try:
            relative = path.resolve().relative_to(context_root.resolve())
        except ValueError:
            relative = Path(path.name)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        copied.append(target)
    return copied


def public_figure_paths(root: Path) -> list[Path]:
    return [root / name for name in PUBLIC_LATITUDE_CAPTIONS if (root / name).is_file()]


def render_public_reproducibility(figures: list[Path], output: Path) -> str:
    cards = []
    for path in figures:
        caption = PUBLIC_LATITUDE_CAPTIONS.get(path.name, path.stem.replace("-", " "))
        src = relpath(path, output)
        cards.append(
            f'<figure class="public-figure"><a href="{esc(src)}"><img src="{esc(src)}" '
            f'alt="{esc(caption)}" loading="lazy"></a><figcaption>{esc(caption)}</figcaption></figure>'
        )
    if not cards:
        return '<p class="muted">Public comparison figures are not present in this build.</p>'
    return f'<div class="public-figure-grid">{"".join(cards)}</div>'


def relpath(path: Path, output_file: Path) -> str:
    return Path(os.path.relpath(path.resolve(), output_file.parent.resolve())).as_posix()


def esc(value: object) -> str:
    return html.escape(str(value))


def crop_viewer_workspace(records: list[dict[str, object]]) -> str:
    if not records:
        return '<p class="muted">No interactive visual review artifacts found yet.</p>'
    viewer_json = json.dumps(records, ensure_ascii=True).replace("<", "\\u003c")
    return """  <section class="crop-workspace" id="cropWorkspace" tabindex="0" aria-labelledby="cropViewerTitle">
    <aside class="crop-sidebar crop-sidebar-left">
      <div class="crop-sidebar-header">
        <strong>Film candidates</strong>
        <span id="cropFilmCount"></span>
      </div>
      <div class="crop-choice-list" id="cropFilmList"></div>
    </aside>
    <section class="crop-stage">
      <div class="crop-toolbar">
        <div>
          <h3 id="cropViewerTitle">Crop Review</h3>
          <p id="cropViewerMeta"></p>
        </div>
        <div class="crop-actions">
          <label class="crop-mode-label">View <select id="cropMode" title="Choose the normal or extreme-edit diagnostic view"></select></label>
          <button type="button" id="cropOverlayToggle" aria-pressed="false" title="Toggle candidate overlay">Overlay</button>
          <button type="button" id="cropZoomOut" title="Zoom out">-</button>
          <button type="button" id="cropZoomIn" title="Zoom in">+</button>
          <button type="button" id="cropReset" title="Reset zoom and pan">Reset</button>
          <button type="button" id="cropFullscreen" aria-pressed="false" title="Enter fullscreen visual review">Fullscreen</button>
        </div>
      </div>
      <canvas id="cropCanvas" role="img" aria-label="Side-by-side crop comparison"></canvas>
      <div class="crop-status" id="cropStatus" aria-live="polite"></div>
    </section>
    <aside class="crop-sidebar crop-sidebar-right">
      <div class="crop-sidebar-header">
        <strong>Candidate quality</strong>
        <span id="cropQualityCount"></span>
      </div>
      <div class="crop-choice-list" id="cropQualityList"></div>
    </aside>
  </section>
  <script type="application/json" id="cropViewerData">__VIEWER_DATA__</script>
  <script>
  (() => {
    const viewers = JSON.parse(document.getElementById("cropViewerData").textContent || "[]");
    const workspace = document.getElementById("cropWorkspace");
    const canvas = document.getElementById("cropCanvas");
    const ctx = canvas.getContext("2d");
    const filmList = document.getElementById("cropFilmList");
    const qualityList = document.getElementById("cropQualityList");
    const filmCount = document.getElementById("cropFilmCount");
    const qualityCount = document.getElementById("cropQualityCount");
    const title = document.getElementById("cropViewerTitle");
    const meta = document.getElementById("cropViewerMeta");
    const status = document.getElementById("cropStatus");
    const overlayToggle = document.getElementById("cropOverlayToggle");
    const fullscreenToggle = document.getElementById("cropFullscreen");
    const modeSelect = document.getElementById("cropMode");
    const imageCache = new Map();
    let loadSerial = 0;
    let activeChoiceList = "film";
    let workspaceActive = false;
    const state = {
      viewerIndex: 0,
      candidateKey: "",
      modeKey: "",
      overlay: false,
      zoom: 1,
      panX: 0,
      panY: 0,
      dragging: false,
      lastX: 0,
      lastY: 0,
      referenceImage: null,
      candidateImage: null,
      referenceOverviewImage: null,
      candidateOverviewImage: null
    };

    if (!viewers.length || !workspace) return;

    function updateFullscreenButton() {
      const active = document.fullscreenElement === workspace;
      fullscreenToggle.textContent = active ? "Exit fullscreen" : "Fullscreen";
      fullscreenToggle.setAttribute("aria-pressed", String(active));
    }

    function currentViewer() {
      return viewers[Math.max(0, Math.min(viewers.length - 1, state.viewerIndex))];
    }

    function currentCandidate() {
      const viewer = currentViewer();
      return viewer.candidates.find((candidate) => candidate.key === state.candidateKey) || viewer.candidates[0];
    }

    function currentMode() {
      const viewer = currentViewer();
      const modes = viewer.metadata.viewModes || [];
      return modes.find((mode) => mode.key === state.modeKey) || modes[0] || { key: "identity", label: "Normal", description: "" };
    }

    function referenceSource(viewer) {
      return (viewer.references && viewer.references[state.modeKey]) || viewer.reference;
    }

    function candidateSource(candidate) {
      return (candidate.sources && candidate.sources[state.modeKey]) || candidate.src;
    }

    function loadImage(src) {
      if (imageCache.has(src)) return imageCache.get(src);
      const promise = new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(src));
        image.src = src;
      });
      imageCache.set(src, promise);
      return promise;
    }

    function resizeCanvas() {
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function fitScale(image, width, height) {
      return Math.min(width / image.width, height / image.height);
    }

    function drawImageFit(image, x, y, width, height, clipRect) {
      if (!image) return;
      ctx.save();
      ctx.beginPath();
      ctx.rect(clipRect[0], clipRect[1], clipRect[2], clipRect[3]);
      ctx.clip();
      ctx.imageSmoothingEnabled = state.zoom < 2;
      const scale = fitScale(image, width, height) * state.zoom;
      const drawnWidth = image.width * scale;
      const drawnHeight = image.height * scale;
      ctx.drawImage(
        image,
        x + (width - drawnWidth) / 2 + state.panX,
        y + (height - drawnHeight) / 2 + state.panY,
        drawnWidth,
        drawnHeight
      );
      ctx.restore();
    }

    function drawOverview(image, x, paneWidth, height) {
      if (!image) return;
      const maxWidth = Math.min(320, paneWidth * .54);
      const maxHeight = Math.min(170, height * .27);
      const scale = Math.min(maxWidth / image.width, maxHeight / image.height);
      const drawnWidth = image.width * scale;
      const drawnHeight = image.height * scale;
      const left = x + (paneWidth - drawnWidth) / 2;
      const top = 12;
      ctx.save();
      ctx.globalAlpha = .92;
      ctx.drawImage(image, left, top, drawnWidth, drawnHeight);
      ctx.strokeStyle = "rgba(255,255,255,.32)";
      ctx.strokeRect(left - .5, top - .5, drawnWidth + 1, drawnHeight + 1);
      ctx.restore();
    }

    function drawPaneLabel(text, x, y) {
      ctx.save();
      ctx.font = "12px Arial, sans-serif";
      const metrics = ctx.measureText(text);
      ctx.fillStyle = "rgba(0,0,0,.62)";
      ctx.fillRect(x + 10, y + 10, metrics.width + 18, 24);
      ctx.fillStyle = "#fff";
      ctx.fillText(text, x + 19, y + 27);
      ctx.restore();
    }

    function draw() {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#101316";
      ctx.fillRect(0, 0, width, height);
      const half = width / 2;
      drawOverview(state.referenceOverviewImage, 0, half, height);
      drawOverview(state.candidateOverviewImage, half, half, height);
      drawImageFit(state.referenceImage, 0, 0, half, height, [0, 0, half, height]);
      drawImageFit(state.candidateImage, half, 0, half, height, [half, 0, half, height]);
      if (state.overlay) {
        drawImageFit(state.candidateImage, 0, 0, half, height, [0, 0, half, height]);
      }
      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,.5)";
      ctx.beginPath();
      ctx.moveTo(half, 0);
      ctx.lineTo(half, height);
      ctx.stroke();
      ctx.restore();
      const candidate = currentCandidate();
      drawPaneLabel(state.overlay ? `${candidate.label} over PS16` : "PS16 reference", 0, 0);
      drawPaneLabel(candidate.label, half, 0);
    }

    async function loadCurrentImages() {
      const serial = ++loadSerial;
      const viewer = currentViewer();
      const candidate = currentCandidate();
      status.textContent = "Loading crop images...";
      try {
        const [referenceImage, candidateImage, referenceOverviewImage, candidateOverviewImage] = await Promise.all([
          loadImage(referenceSource(viewer)),
          loadImage(candidateSource(candidate)),
          viewer.referenceOverview ? loadImage(viewer.referenceOverview) : Promise.resolve(null),
          candidate.overview ? loadImage(candidate.overview) : Promise.resolve(null)
        ]);
        if (serial !== loadSerial) return;
        state.referenceImage = referenceImage;
        state.candidateImage = candidateImage;
        state.referenceOverviewImage = referenceOverviewImage;
        state.candidateOverviewImage = candidateOverviewImage;
        status.textContent = "";
        resizeCanvas();
        draw();
      } catch (error) {
        if (serial !== loadSerial) return;
        status.textContent = "Could not load this crop image.";
      }
    }

    function resetView() {
      state.zoom = 1;
      state.panX = 0;
      state.panY = 0;
    }

    function renderFilmList() {
      filmList.textContent = "";
      filmCount.textContent = `${viewers.length}`;
      viewers.forEach((viewer, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "crop-choice";
        button.setAttribute("aria-pressed", String(index === state.viewerIndex));
        const name = document.createElement("strong");
        name.textContent = viewer.label;
        button.appendChild(name);
        if (viewer.sampleRole) {
          const role = document.createElement("span");
          role.textContent = viewer.sampleRole;
          button.appendChild(role);
        }
        button.addEventListener("click", () => {
          activeChoiceList = "film";
          setViewer(index);
        });
        button.addEventListener("focus", () => { activeChoiceList = "film"; });
        filmList.appendChild(button);
      });
    }

    function renderQualityList() {
      const viewer = currentViewer();
      qualityList.textContent = "";
      qualityCount.textContent = `${viewer.candidates.length}`;
      viewer.candidates.forEach((candidate) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `crop-choice ${candidate.role || ""}`;
        button.setAttribute("aria-pressed", String(candidate.key === state.candidateKey));
        const name = document.createElement("strong");
        name.textContent = candidate.label;
        button.appendChild(name);
        const role = document.createElement("span");
        const roleLabel = candidate.role === "baseline" ? "zero-difference baseline" : candidate.role;
        const sizeLabel = Number.isFinite(candidate.storageMib)
          ? `~${candidate.storageMib.toFixed(1)} MiB ${candidate.storageKind || "stored file"}`
          : "";
        role.textContent = [roleLabel, sizeLabel].filter(Boolean).join(" | ");
        button.appendChild(role);
        button.addEventListener("click", () => {
          activeChoiceList = "quality";
          setCandidate(candidate.key);
        });
        button.addEventListener("focus", () => { activeChoiceList = "quality"; });
        qualityList.appendChild(button);
      });
    }

    function renderModeSelect() {
      const viewer = currentViewer();
      const modes = viewer.metadata.viewModes || [];
      modeSelect.textContent = "";
      modes.forEach((mode) => {
        const option = document.createElement("option");
        option.value = mode.key;
        option.textContent = mode.label || mode.key;
        option.title = mode.description || "";
        modeSelect.appendChild(option);
      });
      modeSelect.value = state.modeKey;
    }

    function updateHeading() {
      const viewer = currentViewer();
      const alignment = viewer.metadata.localRaw61Alignment || {};
      const mode = currentMode();
      title.textContent = viewer.label;
      const parts = [];
      if (viewer.metadata.cropName) parts.push(viewer.metadata.cropName);
      if (mode.label) parts.push(mode.label);
      if (Array.isArray(viewer.metadata.crop) && viewer.metadata.crop.length === 4) parts.push(`crop ${viewer.metadata.crop.join(",")}`);
      if (alignment.applied) parts.push(`RAW61 shift ${alignment.shift_x_px}, ${alignment.shift_y_px}`);
      meta.textContent = `${parts.join(" | ")}${mode.description ? ` - ${mode.description}` : ""}`;
    }

    function setViewer(index) {
      const previousCandidateKey = state.candidateKey;
      const previousModeKey = state.modeKey;
      state.viewerIndex = index;
      const viewer = currentViewer();
      state.candidateKey = viewer.candidates.some((candidate) => candidate.key === previousCandidateKey)
        ? previousCandidateKey
        : (viewer.candidates[0] ? viewer.candidates[0].key : "");
      const modes = viewer.metadata.viewModes || [];
      state.modeKey = modes.some((mode) => mode.key === previousModeKey)
        ? previousModeKey
        : (viewer.metadata.defaultTransform || (modes[0] ? modes[0].key : "identity"));
      resetView();
      renderFilmList();
      renderQualityList();
      renderModeSelect();
      updateHeading();
      loadCurrentImages();
    }

    function setCandidate(key) {
      state.candidateKey = key;
      renderQualityList();
      loadCurrentImages();
    }

    function setMode(key) {
      state.modeKey = key;
      renderModeSelect();
      updateHeading();
      loadCurrentImages();
    }

    function setOverlay(enabled) {
      state.overlay = enabled;
      overlayToggle.setAttribute("aria-pressed", String(enabled));
      overlayToggle.textContent = enabled ? "Side-by-side" : "Overlay";
      draw();
    }

    function moveViewer(delta, preserveActiveList = false) {
      const previousActiveList = activeChoiceList;
      const nextIndex = Math.max(0, Math.min(viewers.length - 1, state.viewerIndex + delta));
      if (nextIndex === state.viewerIndex) return;
      setViewer(nextIndex);
      const button = filmList.querySelectorAll("button")[nextIndex];
      if (button) button.focus();
      if (preserveActiveList) activeChoiceList = previousActiveList;
    }

    function moveCandidate(delta) {
      const candidates = currentViewer().candidates;
      const currentIndex = Math.max(0, candidates.findIndex((candidate) => candidate.key === state.candidateKey));
      const nextIndex = Math.max(0, Math.min(candidates.length - 1, currentIndex + delta));
      if (nextIndex === currentIndex) return;
      setCandidate(candidates[nextIndex].key);
      const button = qualityList.querySelectorAll("button")[nextIndex];
      if (button) button.focus();
    }

    overlayToggle.addEventListener("click", () => setOverlay(!state.overlay));
    modeSelect.addEventListener("change", () => setMode(modeSelect.value));
    document.getElementById("cropZoomOut").addEventListener("click", () => { state.zoom = Math.max(.25, state.zoom / 1.35); draw(); });
    document.getElementById("cropZoomIn").addEventListener("click", () => { state.zoom = Math.min(10, state.zoom * 1.35); draw(); });
    document.getElementById("cropReset").addEventListener("click", () => { resetView(); draw(); });
    fullscreenToggle.addEventListener("click", async () => {
      if (document.fullscreenElement === workspace) await document.exitFullscreen();
      else {
        resetView();
        await workspace.requestFullscreen();
      }
    });
    document.addEventListener("fullscreenchange", () => {
      updateFullscreenButton();
      if (document.fullscreenElement === workspace) resetView();
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => { resizeCanvas(); draw(); });
      });
    });
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      state.zoom = Math.max(.25, Math.min(10, state.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12)));
      draw();
    }, { passive: false });
    canvas.addEventListener("pointerdown", (event) => {
      state.dragging = true;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      canvas.classList.add("dragging");
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!state.dragging) return;
      state.panX += event.clientX - state.lastX;
      state.panY += event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      draw();
    });
    canvas.addEventListener("pointerup", (event) => {
      state.dragging = false;
      canvas.classList.remove("dragging");
      canvas.releasePointerCapture(event.pointerId);
    });
    window.addEventListener("resize", () => {
      resizeCanvas();
      draw();
    });
    document.addEventListener("pointerdown", (event) => {
      workspaceActive = workspace.contains(event.target);
    }, true);
    document.addEventListener("keydown", (event) => {
      if (!workspaceActive && !workspace.contains(document.activeElement)) return;
      if (event.key.toLowerCase() === "o" && !event.target.matches("input,select,textarea")) {
        setOverlay(!state.overlay);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        moveViewer(1, true);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveViewer(-1, true);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (activeChoiceList === "quality") moveCandidate(1);
        else moveViewer(1);
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (activeChoiceList === "quality") moveCandidate(-1);
        else moveViewer(-1);
      }
    });
    setOverlay(false);
    setViewer(0);
  })();
  </script>
""".replace("__VIEWER_DATA__", viewer_json)


def render_html(
    rows: list[dict[str, str]],
    summaries: list[LevelSummary],
    panels: list[Path],
    contexts: list[Path],
    output: Path,
    viewers: list[Path] | None = None,
    annotations: dict[tuple[str, str], dict[str, str]] | None = None,
    public_figures: list[Path] | None = None,
) -> str:
    annotations = annotations or {}
    complete = [row for row in rows if row.get("evidence_status") == "complete"]
    promising = sum(
        1
        for row in complete
        if row.get("verdict") == "ps16_jxl_likely_wins" and row.get("level") not in VISUAL_STRESS_LEVELS
    )
    blocked = len(rows) - len(complete)
    by_verdict = Counter(row.get("verdict", "") for row in rows)
    baselines = summarize_baselines(rows)
    identity_color_values = [item.raw_delta_e_identity for item in baselines if item.raw_delta_e_identity is not None]
    stress_color_values = [item.raw_delta_e_stress for item in baselines if item.raw_delta_e_stress is not None]
    if identity_color_values and stress_color_values:
        stress_review_count = sum(value > 3.0 for value in stress_color_values)
        stress_result = (
            f"In the current {len(stress_color_values)}-frame baseline, normal per-frame patch p95 values span "
            f"{min(identity_color_values):.2f}-{max(identity_color_values):.2f} DeltaE00; after stress they span "
            f"{min(stress_color_values):.2f}-{max(stress_color_values):.2f}, with {stress_review_count} above the "
            "project's DeltaE00 3 review threshold. This says the hard inversion amplifies RAW61-versus-PS16 "
            "workflow differences; it is not JPEG XL codec loss."
        )
    else:
        stress_result = "No complete RAW61 stress-color baseline is available in this build."
    profile = read_profile_flags(DEFAULT_PROFILE)
    raw61_renders, ps16_renders = render_pair_count(DEFAULT_RENDER_INDEX)
    best_zone = [item.level for item in summaries if item.status == "Passes current gates"]
    zone_text = ", ".join(best_zone[:5]) + ("..." if len(best_zone) > 5 else "") if best_zone else "none yet"
    current_conclusion = conclusion_text(summaries)
    viewer_manifest, viewer_index_by_path = viewer_records(viewers or [], output, annotations, rows)
    public_reproducibility_html = render_public_reproducibility(public_figures or [], output)

    level_rows = [lossless_reference_row()]
    for item in summaries:
        size_class = classify_size(item.median_size_pct)
        color_class = classify_delta_e(item.p95_jxl_delta_e)
        color_ratio_class = classify_ratio(item.median_color_ratio)
        structure_ratio_class = classify_ratio(item.median_structure_ratio)
        verdict_class = "unknown" if item.level in VISUAL_STRESS_LEVELS else classify_verdict(item.verdicts)
        verdict_html = (
            "excluded from decision; visual stress reference"
            if item.level in VISUAL_STRESS_LEVELS
            else verdict_text(item.verdicts)
        )
        status_class = level_status_class(item.status)
        level_rows.append(
            f"""
            <tr>
              <td><strong>{esc(item.level)}</strong></td>
              <td class="{status_class}">{esc(item.status)}<br><span class="subtle">{esc(status_reading(item.status))}</span></td>
              <td class="{size_class}"><strong>{fmt_with_unit(item.median_size_pct, 1, "% of RAW61")}</strong><br><span class="subtle">{esc(size_reading(item.median_size_pct))}</span></td>
              <td><strong>{fmt_with_unit(item.median_retained_mib, 1, "MiB")}</strong><br><span class="subtle">JXL median; RAW61 median {fmt_with_unit(item.median_raw61_mib, 1, "MiB")}</span></td>
              <td><strong>{fmt(item.min_size_pct, 1, "%")} - {fmt_with_unit(item.max_size_pct, 1, "% of RAW61")}</strong><br><span class="subtle">{fmt_with_unit(item.min_retained_mib, 1, "MiB")} - {fmt_with_unit(item.max_retained_mib, 1, "MiB")}</span></td>
              <td class="{color_class}"><strong>{fmt_delta_e(item.p95_jxl_delta_e)}</strong><br><span class="subtle">{esc(delta_e_reading(item.p95_jxl_delta_e))}</span></td>
              <td class="{color_ratio_class}"><strong>{fmt_raw61_ratio(item.median_color_ratio)}</strong><br><span class="subtle">{esc(ratio_reading(item.median_color_ratio))}</span></td>
              <td><strong>{fmt_with_unit(item.median_jxl_structure_loss, 3, "loss")}</strong><br><span class="subtle">{esc(structure_reading(item.median_jxl_structure_loss))}</span></td>
              <td class="{structure_ratio_class}"><strong>{fmt_raw61_ratio(item.median_structure_ratio)}</strong><br><span class="subtle">{esc(ratio_reading(item.median_structure_ratio))}</span></td>
              <td class="{verdict_class}">{verdict_html}</td>
            </tr>
            """
        )
    level_chart_html = level_chart(summaries)

    baseline_rows = []
    for item in baselines:
        raw_color_class = classify_delta_e(item.raw_delta_e_stress)
        annotation = annotation_for(item.scan_set, item.set_id, annotations)
        material_label = annotation.get("material_label", item.scan_set)
        role_html = (
            f'<br><span class="subtle">{esc(annotation["sample_role"])}</span>'
            if annotation.get("sample_role")
            else ""
        )
        baseline_rows.append(
            f"""
            <tr>
              <td>{esc(material_label)}{role_html}</td>
              <td><strong>{esc(item.set_id)}</strong></td>
              <td>{fmt(item.raw_delta_e_identity, 2)}</td>
              <td class="{raw_color_class}">{fmt(item.raw_delta_e_stress, 2)}</td>
              <td>{fmt(item.raw_structure_loss, 3)}</td>
              <td>{fmt(item.worst_jxl_delta_e_stress, 2)}</td>
              <td>{fmt(item.worst_jxl_structure_loss, 3)}</td>
            </tr>
            """
        )

    panel_lookup = panel_groups(panels)
    context_lookup = context_groups(contexts)
    viewer_lookup = viewer_groups(viewers or [])
    review_group_set = set(panel_lookup) | set(viewer_lookup)
    if viewer_lookup:
        review_group_set |= set(context_lookup) & review_group_set
    else:
        review_group_set |= set(context_lookup)
    review_groups = sorted(review_group_set)
    visual_review_cards = []
    for group_name in review_groups:
        group_scan_set, group_set_id = group_name.rsplit("/", 1)
        group_annotation = annotation_for(group_scan_set, group_set_id, annotations)
        display_group_name = group_name
        if group_annotation.get("material_label"):
            display_group_name = f'{group_annotation["material_label"]} / {group_set_id}'
        viewer_links = []
        viewer_crop_names = []
        for path in viewer_lookup.get(group_name, []):
            src = relpath(path, output)
            metadata = read_viewer_metadata(path)
            crop_name = str(metadata.get("crop_name") or path.parent.name)
            transform_name = str(metadata.get("transform") or "identity")
            viewer_crop_names.append(crop_name)
            viewer_index = viewer_index_by_path.get(str(path.resolve()), 0)
            viewer_links.append(
                f'<a class="primary-viewer" href="{esc(src)}" data-open-crop-viewer data-viewer-index="{viewer_index}"><strong>Open fullscreen crop viewer</strong><span>{esc(crop_name)} / {esc(transform_name)}</span></a>'
            )
        context_cards = []
        for path in context_lookup.get(group_name, []):
            if viewer_crop_names and not any(path.stem.endswith(f"_{crop_name}") for crop_name in viewer_crop_names):
                continue
            name = path.name
            src = relpath(path, output)
            context_cards.append(
                f'<a class="context-card" href="{esc(src)}"><img src="{esc(src)}" alt="{esc(name)}" loading="lazy"><span>{esc(name)}</span></a>'
            )
        panel_cards = []
        for path in panel_lookup.get(group_name, []):
            name = path.name
            src = relpath(path, output)
            panel_cards.append(
                f'<a class="panel-card" href="{esc(src)}"><img src="{esc(src)}" alt="{esc(name)}" loading="lazy"><span>{esc(name)}</span></a>'
            )
        blocks = []
        if viewer_links:
            blocks.append(f'<div class="primary-viewers">{"".join(viewer_links)}</div>')
        if context_cards:
            blocks.append(f'<h3>Full-frame context</h3><div class="context-grid">{"".join(context_cards)}</div>')
        if panel_cards:
            blocks.append(f'<h3>Static diagnostic panels</h3><div class="panel-grid">{"".join(panel_cards)}</div>')
        if not blocks:
            blocks.append('<p class="muted">No visual artifacts found yet.</p>')
        artifact_count = f"{len(viewer_links)} viewer(s), {len(context_cards)} context image(s)"
        if panel_cards:
            artifact_count += f", {len(panel_cards)} panel(s)"
        visual_review_cards.append(
            f"""
            <section class="review-item">
              <div class="review-heading">
                <h3>{esc(display_group_name)}</h3>
                <span>{esc(artifact_count)}</span>
              </div>
              {''.join(blocks)}
            </section>
            """
        )
    if not visual_review_cards:
        visual_review_cards.append('<p class="muted">No visual review artifacts found yet.</p>')
    visual_review_html = (
        crop_viewer_workspace(viewer_manifest)
        if viewer_manifest
        else "".join(visual_review_cards)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JPEG XL vs RAW61 Break-even Report</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1d2329;
      --muted: #5f6b76;
      --line: #d8dee4;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --good-bg: #dff5e5;
      --good-ink: #14532d;
      --warn-bg: #fff3c4;
      --warn-ink: #7a4b00;
      --risk-bg: #ffe0c2;
      --risk-ink: #8a3a00;
      --bad-bg: #ffd9d9;
      --bad-ink: #8a1f1f;
      --unknown-bg: #eceff3;
      --unknown-ink: #47515c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.45;
    }}
    header, main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    header {{ padding-top: 34px; }}
    h1 {{ font-size: 30px; margin: 0 0 8px; }}
    h2 {{ font-size: 20px; margin: 28px 0 12px; }}
    h3 {{ font-size: 16px; margin: 0 0 8px; }}
    p {{ margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .lead {{ max-width: 980px; font-size: 16px; }}
    .subtle {{ display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    .questions {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .question-card details {{ margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }}
    .question-card summary {{ cursor: pointer; font-weight: 700; color: #075985; }}
    .question-card details p {{ margin: 8px 0 0; color: var(--muted); font-size: 13px; }}
    .public-figure-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .public-figure {{ margin: 0; min-width: 0; }}
    .public-figure a {{ display: block; border: 1px solid var(--line); background: #101316; }}
    .public-figure img {{ display: block; width: 100%; height: auto; }}
    .public-figure figcaption {{ padding: 7px 1px 0; color: var(--muted); font-size: 12px; }}
    .flow {{ display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr); gap: 10px; align-items: stretch; }}
    .flow-col {{ display: grid; gap: 8px; }}
    .flow-box {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; min-height: 82px; }}
    .flow-box strong {{ display: block; margin-bottom: 4px; }}
    .flow-box p {{ font-size: 13px; color: var(--muted); margin: 0; }}
    .arrow {{ display: flex; align-items: center; justify-content: center; color: var(--muted); font-weight: 700; }}
    .adc-disclosure {{ margin-top: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; }}
    .adc-disclosure > summary {{ display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 14px; cursor: pointer; list-style: none; color: #075985; }}
    .adc-disclosure > summary::-webkit-details-marker {{ display: none; }}
    .adc-disclosure > summary::before {{ content: "+"; display: grid; place-items: center; width: 24px; height: 24px; border-radius: 999px; background: #e0f2fe; font-size: 18px; font-weight: 700; line-height: 1; }}
    .adc-disclosure[open] > summary::before {{ content: "−"; }}
    .adc-disclosure > summary:hover {{ background: #f8fafc; }}
    .adc-disclosure-title {{ display: block; font-weight: 700; }}
    .adc-disclosure-subtitle {{ display: block; margin-top: 3px; color: var(--muted); font-size: 13px; font-weight: 400; }}
    .adc-disclosure-action {{ color: var(--muted); font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .adc-disclosure-action::before {{ content: "Show details"; }}
    .adc-disclosure[open] .adc-disclosure-action::before {{ content: "Hide details"; }}
    .adc-disclosure-body {{ padding: 14px; border-top: 1px solid var(--line); }}
    .adc-disclosure-body > :first-child {{ margin-top: 0; }}
    .adc-disclosure-body > :last-child {{ margin-bottom: 0; }}
    .adc-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .adc-item {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .adc-item h3 code {{ font-size: 15px; }}
    .adc-item dl {{ margin: 0; }}
    .adc-item dt {{ margin-top: 10px; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }}
    .adc-item dd {{ margin: 3px 0 0; }}
    .table-scroll {{ width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; border: 1px solid var(--line); background: var(--panel); }}
    .table-scroll table {{ min-width: 1080px; border: 0; }}
    .table-scroll .small-table {{ min-width: 900px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); background: #f0f2f4; position: sticky; top: 0; }}
    thead, th {{ overflow: visible; }}
    .column-help-row th {{ position: static; background: #f8fafc; color: #47515c; font-weight: 400; }}
    .column-help {{ display: block; min-width: 12ch; white-space: normal; font-size: 11px; line-height: 1.4; }}
    abbr {{ text-decoration: underline dotted; cursor: help; }}
    td.good, .pill.good {{ background: var(--good-bg); color: var(--good-ink); }}
    td.warn, .pill.warn {{ background: var(--warn-bg); color: var(--warn-ink); }}
    td.risk, .pill.risk {{ background: var(--risk-bg); color: var(--risk-ink); }}
    td.bad, .pill.bad {{ background: var(--bad-bg); color: var(--bad-ink); }}
    td.unknown, .pill.unknown {{ background: var(--unknown-bg); color: var(--unknown-ink); }}
    .reference-row td {{ background: #f8fafc; }}
    .reference-row td.good {{ background: var(--good-bg); color: var(--good-ink); }}
    .reference-row td.unknown {{ background: var(--unknown-bg); color: var(--unknown-ink); }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; }}
    .panel-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .panel-card {{ display: block; color: inherit; text-decoration: none; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .panel-card img {{ display: block; width: 100%; height: auto; background: #fff; }}
    .panel-card span {{ display: block; padding: 8px 10px; font-size: 13px; color: var(--muted); }}
    .context-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 10px; }}
    .context-card {{ display: block; color: inherit; text-decoration: none; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .context-card img {{ display: block; width: 100%; height: auto; background: #fff; }}
    .context-card span {{ display: block; padding: 8px 10px; font-size: 13px; color: var(--muted); }}
    .viewer-link {{ display: inline-block; margin: 10px 0 2px; color: #075985; font-weight: 700; }}
    .review-item {{ padding: 16px 0; border-top: 1px solid var(--line); }}
    .review-heading {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }}
    .review-heading h3 {{ margin: 0; }}
    .review-heading span {{ color: var(--muted); font-size: 13px; }}
    .review-item h3 {{ margin-top: 16px; }}
    .primary-viewers {{ display: grid; gap: 8px; margin-top: 12px; }}
    .primary-viewer {{ display: flex; flex-direction: column; gap: 2px; padding: 12px; border: 2px solid #075985; background: #eef8ff; color: #075985; text-decoration: none; }}
    .primary-viewer span {{ color: var(--muted); font-size: 13px; }}
    .note {{ border-left: 4px solid #6b7280; padding: 10px 12px; background: #fff; }}
    .small-table th, .small-table td {{ font-size: 13px; }}
    .trend-charts {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0 20px; }}
    .trend-chart {{ margin: 0; padding: 10px; border: 1px solid var(--line); background: var(--panel); }}
    .trend-chart figcaption {{ display: grid; gap: 2px; margin-bottom: 6px; }}
    .trend-chart figcaption span {{ color: var(--muted); font-size: 12px; }}
    .trend-chart svg {{ width: 100%; height: auto; overflow: visible; }}
    .trend-chart text {{ fill: var(--muted); font-size: 10px; }}
    .chart-axis {{ stroke: #aab4be; stroke-width: 1; }}
    .chart-gate {{ stroke: #b45309; stroke-width: 1.5; stroke-dasharray: 4 3; }}
    .chart-bar {{ stroke-width: 1; }}
    .chart-bar-pass {{ fill: #16a36a; stroke: #047857; }}
    .chart-bar-over {{ fill: #f0a23b; stroke: #b45309; }}
    .crop-workspace {{
      display: grid;
      grid-template-columns: minmax(190px, 250px) minmax(0, 1fr) minmax(180px, 220px);
      height: clamp(560px, 72vh, 760px);
      margin-top: 14px;
      overflow: hidden;
      border: 1px solid #2b333b;
      border-radius: 10px;
      background: #0f1215;
      color: #f4f7fa;
    }}
    .crop-sidebar {{
      overflow: auto;
      border-color: #2b333b;
      background: #171b20;
      padding: 12px;
    }}
    .crop-sidebar-left {{ border-right: 1px solid #2b333b; }}
    .crop-sidebar-right {{ border-left: 1px solid #2b333b; }}
    .crop-sidebar-header {{
      position: sticky;
      top: 0;
      z-index: 1;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 0 0 10px;
      background: #171b20;
      color: #f4f7fa;
    }}
    .crop-sidebar-header span {{ color: #a6b0ba; }}
    .crop-choice-list {{ display: grid; gap: 8px; }}
    .crop-choice {{
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 3px;
      border: 1px solid #333d47;
      border-radius: 8px;
      background: #20262d;
      color: #f4f7fa;
      padding: 9px 10px;
      text-align: left;
      cursor: pointer;
    }}
    .crop-choice:hover, .crop-choice[aria-pressed="true"] {{ border-color: #7dd3fc; background: #0c4a6e; }}
    .crop-choice span {{ color: #a6b0ba; font-size: 12px; }}
    .crop-choice[aria-pressed="true"] span {{ color: #d8eefc; }}
    .crop-stage {{ min-width: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; }}
    .crop-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-width: 0;
      padding: 12px 14px;
      border-bottom: 1px solid #2b333b;
      background: #15191e;
    }}
    .crop-toolbar h3 {{ margin: 0 0 3px; color: #f4f7fa; font-size: 18px; }}
    .crop-toolbar p {{ margin: 0; color: #a6b0ba; font-size: 12px; }}
    .crop-actions {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }}
    .crop-actions button {{
      border: 1px solid #3e4a56;
      border-radius: 8px;
      background: #20262d;
      color: #f4f7fa;
      padding: 7px 10px;
      cursor: pointer;
    }}
    #cropOverlayToggle {{ min-width: 116px; text-align: center; }}
    #cropFullscreen {{ min-width: 116px; text-align: center; }}
    .crop-actions button[aria-pressed="true"] {{ background: #075985; border-color: #7dd3fc; }}
    #cropCanvas {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 0;
      background: #101316;
      cursor: grab;
      touch-action: none;
    }}
    #cropCanvas.dragging {{ cursor: grabbing; }}
    .crop-status {{ min-height: 28px; padding: 6px 14px; color: #a6b0ba; background: #15191e; }}
    .crop-workspace:fullscreen {{ width: 100vw; height: 100vh; max-width: none; margin: 0; border-radius: 0; }}
    ul {{ margin-top: 8px; }}
    @media (max-width: 1150px) {{
      .crop-toolbar {{ align-items: flex-start; flex-direction: column; }}
      .crop-actions {{ width: 100%; justify-content: flex-start; }}
    }}
    @media (max-width: 900px) {{
      .grid, .questions, .adc-grid, .panel-grid, .context-grid, .flow, .trend-charts, .public-figure-grid {{ grid-template-columns: 1fr; }}
      .arrow {{ display: none; }}
      header, main {{ padding: 16px; }}
      table {{ font-size: 13px; }}
      .review-heading {{ align-items: flex-start; flex-direction: column; }}
      .crop-workspace {{ height: auto; grid-template-columns: 1fr; grid-template-rows: auto minmax(58vh, 620px) auto; }}
      .crop-sidebar {{ max-height: 220px; }}
      .crop-sidebar-left, .crop-sidebar-right {{ border: 0; border-bottom: 1px solid #2b333b; }}
      .crop-sidebar-right {{ border-top: 1px solid #2b333b; }}
    }}
    @media (max-width: 700px) {{
      header, main {{ padding: 12px; }}
      h1 {{ font-size: 25px; }}
      .table-scroll {{ border-left: 0; border-right: 0; }}
      .table-scroll th:first-child, .table-scroll td:first-child {{
        position: sticky;
        left: 0;
        z-index: 2;
        background: var(--panel);
        box-shadow: 1px 0 0 var(--line);
      }}
      .table-scroll thead th:first-child {{ z-index: 4; background: #f0f2f4; }}
      .table-scroll .column-help-row th:first-child {{ background: #f8fafc; }}
      .crop-workspace {{ grid-template-rows: auto minmax(68vh, 600px) auto; border-radius: 8px; }}
      .crop-sidebar {{ max-height: 178px; padding: 10px; }}
      .crop-choice-list {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 3px; }}
      .crop-choice {{ flex: 0 0 min(76vw, 260px); }}
      .crop-toolbar {{ padding: 10px; }}
      .crop-actions {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }}
      .crop-mode-label {{ grid-column: 1 / -1; width: 100%; }}
      .crop-mode-label select {{ display: block; width: 100%; min-width: 0; margin-top: 3px; }}
      .crop-actions button {{ min-width: 0; padding: 8px 5px; white-space: nowrap; }}
      #cropOverlayToggle, #cropFullscreen {{ min-width: 0; grid-column: span 2; }}
      #cropReset {{ grid-column: span 2; }}
      #cropCanvas {{ min-height: 420px; }}
      .crop-workspace:fullscreen {{ overflow-y: auto; grid-template-rows: auto minmax(58vh, 1fr) auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>JPEG XL vs RAW61 Break-even Report</h1>
    <p class="lead">This report asks whether a 240 MP PixelShift 16 capture stored as JPEG XL can preserve more archival value than a conventional 61 MP RAW file at roughly the <em>same storage cost</em>. The motive is practical: camera scanning can capture more useful film detail with PixelShift, but RAW/DNG storage grows fast enough to become the limiting factor for a real archive.</p>
    <p class="muted">Because much of the material is color negative film, inversion matters: small color or tone losses hidden inside the orange mask can be amplified when the negative is inverted and corrected. Current build from local test material. The page publishes selected small review artifacts only; full-resolution source files stay outside the site artifact.</p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><h3>Candidate Comparisons</h3><div class="metric">{len(rows)}</div><p class="muted">each comparison is one film material &times; frame &times; JXL distance</p></div>
      <div class="card"><h3>Fully Measured Comparisons</h3><div class="metric">{len(complete)}</div><p class="muted">comparisons with all three required measurements: file size, color and structure</p></div>
      <div class="card"><h3>Decision-grade Favorable Comparisons</h3><div class="metric">{promising}</div><p class="muted">fully measured candidate comparisons favoring PS16 JXL; deliberately aggressive visual-stress levels are excluded</p></div>
      <div class="card"><h3>Median-size Budget Levels</h3><div class="metric">{esc(zone_text)}</div><p class="muted">JXL levels whose median file size is no larger than paired RAW61; this is a size result, not a quality verdict</p></div>
    </section>

    <h2>Current Reading</h2>
    <div class="note">
      <p><strong>{current_conclusion}</strong></p>
      <p>The current numeric result is provisional because the RAW61 baseline includes render-profile, demosaic/acutance and registration effects, while PS16 JXL is measured against the PS16 render. This compares two archival workflows, not sensor resolution in isolation. Codec damage and RAW61-vs-PS16 baseline differences are therefore reported separately, with registered crop comparisons provided below for visual inspection.</p>
    </div>

    <h2>What Are We Asking?</h2>
    <section class="questions">
      <div class="card question-card">
        <h3>1. Codec question</h3>
        <p><strong>PS16 reference vs PS16 JXL.</strong> This is apples-to-apples and measures JPEG XL damage to a fixed rendered image state.</p>
        <details>
          <summary>Answer so far</summary>
          <p>The tested lossy levels show very small patch color movement (small shifts in the measured average color of sampled image areas) against the PS16 reference. Codec damage is not zero, and the trained eye can still see grain/texture changes, so this remains a quality-threshold question rather than a pure pass/fail.</p>
        </details>
      </div>
      <div class="card question-card">
        <h3>2. Archive-value question</h3>
        <p><strong>PS16 JXL vs RAW61.</strong> This is intentionally a workflow tradeoff: more sampling plus lossy coding versus less sampling plus raw preservation.</p>
        <details>
          <summary>Answer so far</summary>
          <p>Current complete rows favor PS16 JXL in {promising} of {len(complete)} comparisons, but RAW61 still has raw-edit latitude and fewer workflow assumptions. This is why the report separates codec damage from the broader archive-value verdict.</p>
        </details>
      </div>
      <div class="card question-card">
        <h3>3. Break-even question</h3>
        <p>At what JXL distance does PS16 JXL stop carrying more useful film information than RAW61 at the same storage budget?</p>
        <details>
          <summary>Answer so far</summary>
          <p>{current_conclusion} The levels currently below the RAW61 median-size budget are {esc(zone_text)}. This size result is not a quality verdict; the boundary still needs more film material and visual review before it should be treated as a general recommendation.</p>
        </details>
      </div>
      <div class="card question-card">
        <h3>4. Operational question</h3>
        <p>Can the retained files remain decodable, documented, color-managed, and practical as archive masters or secondary masters?</p>
        <details>
          <summary>Answer so far</summary>
          <p>Standalone rendered PS16 JXL is the active archive candidate and is decodable with standard JPEG XL tools, but metadata must be carried in documented sidecars. ADC DNG/JXL is excluded from the core verdict because current local tests found incompatible rendering plus metadata and geometry rewrites.</p>
        </details>
      </div>
    </section>

    <h2>Workflow Being Tested</h2>
    <section class="flow">
      <div class="flow-col">
        <div class="flow-box"><strong>Film frame</strong><p>Negative or positive original. The physical object is the real source, not any file.</p></div>
      </div>
      <div class="arrow">&rarr;</div>
      <div class="flow-col">
        <div class="flow-box"><strong>61 MP RAW</strong><p>Single-shot Bayer capture. Strong raw edit latitude, less spatial sampling.</p></div>
        <div class="flow-box"><strong>240 MP PS16 DNG</strong><p>PixelShift2DNG output. More spatial sampling, very large retained files.</p></div>
      </div>
      <div class="arrow">&rarr;</div>
      <div class="flow-col">
        <div class="flow-box"><strong>Fixed render state</strong><p>RawTherapee neutral render. Used so comparisons measure declared outputs, not random app defaults.</p></div>
        <div class="flow-box"><strong>ADC DNG/JXL (excluded)</strong><p>Measured side path, excluded from the core verdict because of application, metadata and geometry changes.</p></div>
      </div>
      <div class="arrow">&rarr;</div>
      <div class="flow-col">
        <div class="flow-box"><strong>Standalone PS16 JXL</strong><p>Main tested candidate now. Codec damage is measured against the PS16 render.</p></div>
        <div class="flow-box"><strong>Keep original RAW/DNG</strong><p>Safest archive branch. Expensive in storage; remains the conservative recommendation.</p></div>
      </div>
      <div class="arrow">&rarr;</div>
      <div class="flow-col">
        <div class="flow-box"><strong>Break-even verdict</strong><p>Size, color/tone, structure, visual review and operational risk are combined.</p></div>
      </div>
    </section>

    <h2>ADC DNG/JXL</h2>
    <div class="note">
      <p><strong>Current conclusion:</strong> Adobe DNG Converter 18.5 can create DNG 1.7 files with internal JPEG XL, and the tested lossless low-level crops were exact. Lossy ADC rewrites the image state and is not usable in the project's reference renderer, so this path is excluded from the core break-even verdict. The active candidate is standalone JXL from a fixed 16-bit PS16 render.</p>
    </div>
    <details class="adc-disclosure">
      <summary>
        <span>
          <span class="adc-disclosure-title">Why ADC DNG/JXL Was Excluded</span>
          <span class="adc-disclosure-subtitle">Nine documented findings covering geometry, sample interpretation, application support, visual validation, and storage.</span>
        </span>
        <span class="adc-disclosure-action" aria-hidden="true"></span>
      </summary>
      <div class="adc-disclosure-body">
        <p><strong>How to read the list:</strong> “confirmed” records something observed in the local files or application probe. “Open validation” identifies evidence that would be required before reconsidering this path; it is not part of the current work queue.</p>
        <section class="adc-grid">
      <div class="adc-item">
        <h3>Stored image shape <span class="pill risk">Confirmed rewrite</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>In the active PixelShift 16 batches, lossy ADC changed the main raster from <code>19200&times;12752</code> to <code>19120&times;12736</code>. The small earlier smoke-test files showed the same pattern at <code>9600&times;6376</code> to <code>9552&times;6360</code>. Lossless ADC kept the source shape.</dd>
          <dt>Actual problem</dt>
          <dd>The lossy file no longer has the source file's stored pixel grid. This may be a valid flattening of the active area, but direct pixel indexing and geometry metadata from the source are no longer interchangeable.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Compare the same active image area through a crop-aware renderer, confirm that no useful edge pixels or placement information are lost, and keep the source DNG until that result is reproducible.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>Crop origin / active placement <span class="pill risk">Confirmed rewrite</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>The active crop origin changed from <code>[8, 8]</code> in the source to <code>[0, 0]</code> in every checked lossy candidate. This is consistent with ADC writing the active area as the new stored raster.</dd>
          <dt>Actual problem</dt>
          <dd>The coordinate system changed. Copying the old crop tag back would shift the image or trim a second time; comparing the two rasters without applying their own crop metadata would compare different locations.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Verify placement in at least two independent full DNG render paths and compare registered active areas rather than raw array coordinates.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3><code>WhiteLevel</code> <span class="pill risk">Confirmed rewrite</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>Lossy ADC changed all three channel values from <code>14848</code> to <code>65535</code>. Lossless ADC retained <code>14848</code>.</dd>
          <dt>Actual problem</dt>
          <dd>The stored sample domain was rescaled. Restoring the old tag or dividing both files by one assumed scale can produce false tone, clipping, or highlight-recovery differences.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Use each file's declared scale, apply its required opcodes, then test clipping and recoverable latitude through the same trusted renderer. The current low-level normalization is diagnostic evidence, not a restoration of the original raw-scale semantics.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3><code>OpcodeList2</code> <span class="pill risk">Confirmed dependency</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>The checked lossy files added three channel-specific <code>MapPolynomial</code> operations where the source had no <code>OpcodeList2</code>. Applying those maps removed the large false domain mismatch in the first raster comparison.</dd>
          <dt>Actual problem</dt>
          <dd>A decoder that extracts the JXL pixels but ignores the DNG opcodes does not recover the intended linear values. Correct rendering now depends on complete support for this processing step.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Confirm the same result in independent DNG renderers and record which archive applications apply the opcode correctly. Copying or deleting the opcode is not a safe repair.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>Lossy embedded color path <span class="pill warn">Confirmed sample, limited scope</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>Representative main-image tiles from two local files used the JPEG XL XYB path for lossy <code>d=0.05</code>; lossless main-image tiles used the original-profile, non-XYB path. The outer DNG still labels the image <code>LinearRaw</code>.</dd>
          <dt>Actual problem</dt>
          <dd>The lossy path is not a direct preservation of camera-native linear channel samples. A perceptual transform may behave well for normal viewing yet respond differently to negative inversion, channel balancing, or future extreme edits.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Inspect representative tiles across the corpus and run the actual ADC output through the same post-inversion and grading tests used for the archive decision.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>RawTherapee compatibility <span class="pill bad">Confirmed incompatibility</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>A local RawTherapee 5.12 CLI probe returned <code>Error loading file</code> for both one lossless ADC DNG/JXL and its lossy <code>d=0.05</code> counterpart. The source PixelShift2DNG files are already rendered by the same workflow.</dd>
          <dt>Actual problem</dt>
          <dd>The project cannot feed source and ADC candidate into its one fixed RawTherapee render pipeline. This is a concrete workflow incompatibility, not evidence that the embedded JXL pixels are corrupt.</dd>
          <dt>Required before reconsideration</dt>
          <dd>A RawTherapee version that opens and correctly processes DNG 1.7/JXL, or another trusted renderer that can render both sides with equivalent settings and documented color handling.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>Independent full-DNG decode <span class="pill unknown">Open validation</span></h3>
        <dl>
          <dt>What exists</dt>
          <dd>The project can extract main-image JXL tiles, decode matched crop windows, normalize by the declared white level, and apply the observed <code>MapPolynomial</code> opcodes. Lossless crops are exact through that path.</dd>
          <dt>Actual missing evidence</dt>
          <dd>This custom low-level check is not a second complete DNG implementation. It does not prove that crop, color matrices, opcodes, previews, and metadata are interpreted consistently by independent archive applications.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Matching color-managed renders from at least one independent DNG/JXL-capable application, followed by an application matrix for the tools expected in the real workflow.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>Real edit and visual review <span class="pill unknown">Open validation</span></h3>
        <dl>
          <dt>What exists</dt>
          <dd>Low-level crop metrics already show the expected ordering: lossless is exact, <code>d=0.03</code> is cleaner than <code>d=0.05</code>, and <code>d=0.10</code> develops a much worse error tail after negative-like stress.</dd>
          <dt>Actual missing evidence</dt>
          <dd>There is no blinded, end-to-end comparison of source and ADC DNG/JXL after a real color-managed inversion and grading workflow. Low average patch color error does not rule out objectionable grain, texture, or local-density changes.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Registered same-render outputs, clipping and latitude checks, and blinded visual review on representative real negatives.</dd>
        </dl>
      </div>
      <div class="adc-item">
        <h3>Storage-budget coverage <span class="pill bad">Not reached</span></h3>
        <dl>
          <dt>Observed</dt>
          <dd>Lossless ADC retained roughly <code>85-97%</code> of the source PS16 DNG size in complete local rows. Even the tested lossy <code>d=0.10</code> files were about <code>161-888%</code> of their paired 61 MP raw files.</dd>
          <dt>Actual problem</dt>
          <dd>The tested conservative ADC levels do not answer the project's same-storage question. They reduce PS16 storage substantially but remain larger than the RAW61 budget.</dd>
          <dt>Required before reconsideration</dt>
          <dd>Generate and validate an ADC distance bracket that actually crosses the paired RAW61 size, or report ADC as a separate larger-budget candidate. The current main break-even result therefore uses standalone JXL from a fixed PS16 render.</dd>
        </dl>
      </div>
        </section>
      </div>
    </details>

    <h2>Level Summary</h2>
    <div class="note">
      <p><strong>What this table is for:</strong> compare JPEG XL distance levels. RAW61 baselines are moved to the next table because they do not change when the JXL distance changes.</p>
      <p><strong>Decision gate:</strong> a level is only treated as a current PS16 JXL win when it is at or below the RAW61 storage budget and remains closer to the PS16 reference than RAW61 does for the current color and structure diagnostics.</p>
      <p><strong>Lossless row:</strong> shown as a zero-codec-loss reference. It is not counted as a break-even candidate until complete standalone lossless size rows are generated for the same material.</p>
      <p><strong>Important:</strong> the colors below are diagnostic labels, not FADGI conformance claims. FADGI-style target measurements are interpretation anchors because this project compares rendered film scans and compression candidates, not calibrated capture-target conformance.</p>
    </div>
    <section class="questions">
      <div class="card"><h3>Size</h3><p>Answers whether the retained PS16 JXL candidate fits inside the paired RAW61 storage budget. Values over 100% are larger than RAW61.</p></div>
      <div class="card"><h3>JXL color p95</h3><p>The reference and candidate receive the same deterministic hard inversion. The image is then divided into 256-pixel patches at the analysis resolution. Each patch is averaged in linear ProPhoto RGB before conversion to Lab. Each frame reports patch p95; this level table reports p95 again across those frame values. Below 1 is small; this tests mean color and tone under stress, not grain shape.</p></div>
      <div class="card"><h3>Color ratio</h3><p>JXL color movement divided by RAW61-vs-PS16 color baseline. Below 1 means JXL is closer to PS16 than RAW61 is for this metric.</p></div>
      <div class="card"><h3>Structure ratio</h3><p>Luminance minus a 5&times;5 local blur isolates fine-scale variation. The RMS difference between candidate and PS16 high-pass images is divided by the PS16 high-pass RMS. The ratio column then divides this result by RAW61's result. Below 1 means JXL is closer to PS16 for this diagnostic. It reacts to grain, edges, acutance, noise and residual alignment, so it is not a literal percentage of detail destroyed.</p></div>
    </section>
    <div class="table-scroll" tabindex="0" role="region" aria-label="JPEG XL level summary; scroll horizontally on small screens"><table>
      <thead>
        <tr>
          <th>{abbr("JXL level", "JPEG XL distance label. d030 means distance 0.30.")}</th>
          <th>{abbr("Current gate", "Plain-language gate combining size and current diagnostics. Too large means the image metrics may be good, but the file is still larger than the paired RAW61 target.")}</th>
          <th>{abbr("Median size (% RAW61)", "Median retained JXL size as percent of paired 61 MP raw size. Below 100% is within budget.")}</th>
          <th>{abbr("Median retained size (MiB)", "Median encoded JXL file size, with paired RAW61 median shown for context.")}</th>
          <th>{abbr("Size range (% RAW61 / MiB)", "Smallest to largest size-vs-RAW61 and encoded MiB across complete frame pairs.")}</th>
          <th>{abbr("JXL color p95 (DeltaE00)", "95th percentile across frame-level JXL patch p95 DeltaE00 after a post-codec negative-density inversion proxy. Measures codec color/tone movement under stress.")}</th>
          <th>{abbr("Color loss ratio (x RAW61)", "Median JXL color loss divided by RAW61 color baseline. Below 1 means JXL is closer to PS16 than RAW61 is.")}</th>
          <th>{abbr("JXL structure error (fraction of PS16 detail RMS)", "Median normalized high-pass error for JXL versus PS16. 0 is exact; 0.20 means the error RMS equals 20% of the PS16 high-frequency RMS, not that 20% of detail was destroyed.")}</th>
          <th>{abbr("Structure ratio (x RAW61)", "Median JXL structure loss divided by RAW61 structure baseline. Below 1 means JXL is structurally closer to PS16 than RAW61 is.")}</th>
          <th>{abbr("Verdicts", "Counts of conservative matrix verdicts for this level.")}</th>
        </tr>
        <tr class="column-help-row">
          {column_help("Codec setting", "JPEG XL distance label. d020 means distance 0.20, d030 means distance 0.30. Higher distance usually means smaller files and more loss. Lossless is a reference row, not a break-even candidate.")}
          {column_help("Decision label", "Plain-language status after combining size and the current diagnostics. Too large means the image metrics may still look strong, but the median file size is above the paired RAW61 budget.")}
          {column_help("Storage budget", "Median retained standalone PS16 JXL size divided by paired 61 MP RAW size. 100% means the same storage cost as RAW61; below 100% means the JXL candidate is smaller.")}
          {column_help("Actual size", "Median encoded standalone JXL file size in mebibytes. The small text also shows the paired RAW61 median size, so the percent budget can be checked in normal file-size units.")}
          {column_help("Spread", "Minimum and maximum retained JXL size across complete frame pairs, shown both as percent of RAW61 and as encoded MiB. Wide ranges mean the level depends strongly on image content.")}
          {column_help("Color stress", "Both images receive one fixed, reference-derived density inversion. At the analysis scale, 256 x 256-pixel patches are averaged in linear ProPhoto RGB, converted to Lab, and compared with CIEDE2000. This value is the 95th percentile across frames of each frame's patch p95: 95% of sampled areas in a typical frame are no worse. Lower is better; it measures mean color/tone movement, not grain.")}
          {column_help("Color vs RAW61", "Median JXL color movement divided by the RAW61-vs-PS16 color baseline. Below 1 means JXL stays closer to PS16 than RAW61 does for this diagnostic.")}
          {column_help("Normalized detail error", "For each image, luminance minus a 5 x 5 local blur isolates fine structure. We take the RMS of candidate-minus-reference high-pass values and divide by the RMS of the PS16 high-pass reference. Thus 0 is exact and 0.20 means error RMS is 20% of the reference's fine-structure RMS. It can reflect grain, edges, acutance or noise and must be checked visually.")}
          {column_help("Detail vs RAW61", "Median JXL high-pass detail loss divided by RAW61 high-pass detail loss after registration. Below 1 means the JXL candidate remains structurally closer to PS16 than RAW61.")}
          {column_help("Row verdicts", "Counts of per-frame verdict labels at this JXL level. These counts explain whether the summary is broad or driven by a few frames.")}
        </tr>
      </thead>
      <tbody>
        {''.join(row.strip() for row in level_rows)}
      </tbody>
    </table></div>

    <h3>How The Tested Levels Move</h3>
    <p class="muted">The bars treat each tested JXL setting as a discrete category because the sampled distance values are unevenly spaced. Each chart has its own vertical scale. The dashed line is the RAW61 comparison gate: 100% for storage and 1.0x for the two relative-error measures.</p>
    {level_chart_html}

    <h2>Color Legend And Units</h2>
    <section class="questions">
      <div class="card"><h3>Current gate</h3><p><span class="pill good">green</span> means the level passes the current size, color and structure gates. <span class="pill warn">yellow</span> means review zone. <span class="pill bad">red</span> means too large or image risk. This is a decision label, not a measured unit.</p></div>
      <div class="card"><h3>Size cells</h3><p>Unit: percent of paired RAW61 size, plus encoded MiB. <span class="pill good">green</span> is at or below 100% RAW61. <span class="pill warn">yellow</span> is up to 115%. <span class="pill bad">red</span> is clearly over the RAW61 storage budget.</p></div>
      <div class="card"><h3>&Delta;E00 cells</h3><p>Unit: CIEDE2000 color difference. The table uses patch p95 after the current negative-density stress transform. <span class="pill good">green</span> is below 1. <span class="pill warn">yellow</span> is 1-2. <span class="pill risk">orange</span> is 2-3. <span class="pill bad">red</span> is above 3.</p></div>
      <div class="card"><h3>Ratio cells</h3><p>Unit: multiple of the RAW61-vs-PS16 baseline. Example: 0.25x RAW61 means one quarter of the RAW61 baseline error. Values below 1 favor PS16 JXL for that metric.</p></div>
      <div class="card"><h3>Structure cells</h3><p>The value is normalized high-pass error: error RMS divided by PS16 high-frequency RMS. <code>0.000</code> is exact; <code>0.200</code> means the mismatch RMS is 20% of the reference's fine-structure RMS. It does not mean 20% of real detail vanished. The color-coded ratio compares like-for-like against RAW61; below 1 favors JXL.</p></div>
      <div class="card"><h3>FADGI note</h3><p>These colors are interpretation aids, not formal FADGI conformance. The useful FADGI lesson here is to keep color, tone, registration, sharpening, noise and structure separate instead of collapsing everything into one score.</p></div>
    </section>

    <h2>RAW61 Baseline By Frame</h2>
    <div class="note">
      <p><strong>What this table is for:</strong> show the apples-to-oranges part explicitly. RAW61 values are frame baselines: they are expected to repeat across JXL levels and should be reviewed for alignment, acutance, color profile and tone differences.</p>
      <p><strong>How to read stress color:</strong> RAW61 and PS16 are first registered and rendered through the declared neutral pipeline. The same PS16-derived normalization, logarithmic transmission-to-density conversion, clipping, fixed channel balance and steep contrast curve are then applied to both. Patch means are compared as &Delta;E00. A much larger stress value than normal color means differences that look modest in the negative become prominent after this deliberately severe inversion. It is a reproducible sensitivity test, not a FilmLab simulation or a claim that PS16 is ground truth.</p>
      <p><strong>Current result:</strong> {esc(stress_result)}</p>
    </div>
    <div class="table-scroll" tabindex="0" role="region" aria-label="RAW61 baseline by frame; scroll horizontally on small screens"><table class="small-table">
      <thead>
        <tr>
          <th>{abbr("Scan set", "Local scan folder / material label.")}</th>
          <th>{abbr("Frame", "Capture set id.")}</th>
          <th>{abbr("RAW61 color", "RAW61 vs PS16 patch p95 DeltaE00 before stress.")}</th>
          <th>{abbr("RAW61 stress color", "RAW61 vs PS16 patch p95 DeltaE00 after hard negative-density transform.")}</th>
          <th>{abbr("RAW61 structure", "RAW61 normalized high-pass error against PS16 after registration: error RMS divided by PS16 high-frequency RMS.")}</th>
          <th>{abbr("Worst JXL color", "Worst JXL stress DeltaE00 across levels currently in the matrix.")}</th>
          <th>{abbr("Worst JXL structure", "Largest normalized JXL high-pass error across levels currently in the matrix.")}</th>
        </tr>
        <tr class="column-help-row">
          {column_help("Material group", "Scan collection or material label. Rows with the same name belong to the same film, target, or source batch, but each frame is evaluated separately.")}
          {column_help("Capture id", "Specific frame or capture-set identifier used to join the paired RAW61, PS16 reference, and JXL evidence for this row.")}
          {column_help("Baseline color", "95th-percentile patch CIEDE2000 difference for RAW61 versus the PS16 reference before the negative-density stress transform. Lower means the RAW61 render is closer to PS16; this is not JXL codec loss.")}
          {column_help("Baseline under stress", "After registration, both RAW61 and PS16 receive the same reference-derived density mapping: normalize transmission, convert with -log(), clip the outer range, apply one fixed channel balance, then a steep contrast curve. We average 256 x 256-pixel patches in linear ProPhoto RGB, convert means to Lab, and report patch p95 DeltaE00. Higher than baseline color means inversion amplifies workflow differences; it does not isolate the codec or emulate a specific film scanner.")}
          {column_help("Baseline detail", "Normalized high-pass error for RAW61 versus PS16 after registration. Luminance minus a 5 x 5 blur isolates fine variation; difference RMS is divided by PS16 high-pass RMS. 0 is exact and 1 means mismatch RMS equals the reference fine-structure RMS. Capture, demosaic, acutance, noise and residual alignment all contribute; this is not codec loss.")}
          {column_help("Worst codec color", "Largest PS16 JXL-versus-PS16 stress DeltaE00 found across the JXL levels currently included for this frame. It identifies the most color-disruptive tested level; lower is better.")}
          {column_help("Worst codec detail", "Largest normalized PS16 JXL-versus-PS16 high-pass error across included JXL levels. 0 is exact; 0.20 means error RMS is 20% of the PS16 fine-structure RMS. It can expose altered grain, edges or noise but is not a direct percentage of lost information; inspect important crops in the viewer.")}
        </tr>
      </thead>
      <tbody>
        {''.join(row.strip() for row in baseline_rows)}
      </tbody>
    </table></div>

    <h2>Render/Profile Audit</h2>
    <section class="questions">
      <div class="card"><h3>Current profile</h3><p><code>{esc(DEFAULT_PROFILE.relative_to(ROOT))}</code></p><p class="muted">Render index contains {raw61_renders} RAW61 rows and {ps16_renders} PS16 rows.</p></div>
      <div class="card"><h3>Color management</h3><p>Input profile: <code>{esc(profile["input_profile"])}</code><br>Working profile: <code>{esc(profile["working_profile"])}</code><br>Output profile: <code>{esc(profile["output_profile"])}</code></p></div>
      <div class="card"><h3>White balance warning</h3><p>WB enabled: <code>{esc(profile["white_balance_enabled"])}</code><br>WB setting: <code>{esc(profile["white_balance_setting"])}</code></p><p class="muted">Camera WB can differ between ARW and PixelShift2DNG metadata, so RAW61 may render less orange even with the same profile file.</p></div>
      <div class="card"><h3>Detail handling</h3><p>RAW Bayer demosaic: <code>{esc(profile["raw_bayer_method"])}</code><br>Sharpening enabled: <code>{esc(profile["sharpening_enabled"])}</code></p><p class="muted">Apparent RAW61 sharpness can still come from demosaic/acutance, scaling and local alignment.</p></div>
    </section>

    <h2>Visual Review</h2>
    <div class="note">
      <p><strong>What this section is for:</strong> inspect the actual image differences behind the numeric table in one shared comparison workspace.</p>
      <p>Select a film crop on the left and a quality candidate on the right. The viewer supports side-by-side comparison, overlay, zoom, pan, and keyboard navigation without leaving the report.</p>
    </div>
    {visual_review_html}

    <h2>Public Reproducibility Check</h2>
    <div class="note">
      <p><strong>What this adds:</strong> the same JPEG XL and post-codec density-inversion stress pipeline was run on six public images: three FADGI/OpenDICE transmissive targets and three Library of Congress photographs. This makes the codec behavior reproducible without publishing the private full-resolution film scans.</p>
      <p><strong>Result:</strong> across the six 2048-pixel test crops, <code>d=0.03</code> was cleanest, <code>d=0.05</code> remained the conservative lossy candidate, and <code>d=0.10</code> produced larger errors. The hard density transform amplified errors that were less prominent in the unchanged image. Each panel shows reference, decoded JXL, amplified absolute difference, and amplified signed difference.</p>
      <p><strong>Boundary:</strong> these TIFFs test codec and stress-transform behavior. They do not contain paired RAW61 and PS16 camera captures, so they do not contribute rows to the storage break-even verdict.</p>
      <p><a href="https://github.com/hsnilsson/jpegxl-vs-dngpixelshift/blob/main/docs/public-latitude-v2.md">Method, metrics, provenance, and complete public-test interpretation</a></p>
    </div>
    {public_reproducibility_html}

    <h2>FADGI Context</h2>
    <div class="card">
      <p>Useful established metrics include CIEDE2000 color accuracy, tone response, white balance error, color-channel misregistration, SFR/sampling efficiency, sharpening, and noise. The relevant lesson for this project is not that our film-crop rows can claim FADGI stars, but that a credible imaging study should separate color, tone, registration, detail, sharpening, and noise instead of relying on PSNR or a single diff image.</p>
      <ul>
        <li>Official FADGI 2023 guidelines describe the still-image conformance system and its target/software basis.</li>
        <li>FADGI/related practice commonly uses &Delta;E00 for color accuracy; strict published discussions cite average &Delta;E00 around 2 for highest-level color profiling, while older/practical references often discuss average 3 and maximum 6 as useful limits.</li>
        <li>NARA permanent-record rules expose related concrete thresholds: average color accuracy &lt;3.5 &Delta;E00, 90th percentile &lt;8.75, color-channel misregistration &lt;0.5 px, sharpening max modulation &lt;1.1, and noise upper limit &lt;2 L* std dev for the listed record category.</li>
      </ul>
      <p class="muted">Sources: FADGI Technical Guidelines page, FADGI Resources page, NARA 36 CFR 1236.50, and Heritage Science discussion of FADGI color tolerances.</p>
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local HTML report for the break-even study.")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--panels", type=Path, default=DEFAULT_PANELS)
    parser.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--copy-panels-to",
        type=Path,
        help="Copy selected review panels into this asset directory before linking them. Useful for publishing site/.",
    )
    parser.add_argument(
        "--include-panels",
        action="store_true",
        help="Include static diagnostic panels in the report. Omit for the public site build; they are large regenerated artifacts.",
    )
    parser.add_argument(
        "--copy-contexts-to",
        type=Path,
        help="Copy small full-frame context thumbnails into this asset directory before linking them.",
    )
    parser.add_argument(
        "--viewers",
        type=Path,
        default=None,
        help="Optional root containing generated interactive review viewers.",
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS,
        help="Optional JSON annotations for correcting presentation labels without changing source metrics.",
    )
    parser.add_argument(
        "--public-figures",
        type=Path,
        default=DEFAULT_PUBLIC_FIGURES,
        help="Directory containing selected public latitude-stress figures.",
    )
    parser.add_argument(
        "--copy-public-figures-to",
        type=Path,
        help="Copy selected public figures into the report artifact before linking them.",
    )
    parser.add_argument(
        "--exclude-cases-file",
        type=Path,
        default=DEFAULT_EXCLUDE_CASES,
        help='Optional denylist with one "scan_set_or_slug|set_id" per line.',
    )
    parser.add_argument(
        "--exclude-case",
        action="append",
        default=None,
        help='Exclude one case from report rows and image assets as "scan_set_or_slug|set_id". Repeatable.',
    )
    args = parser.parse_args()

    excludes = read_exclude_cases(args.exclude_cases_file, args.exclude_case)
    annotations = read_annotations(args.annotations)
    rows = filter_rows(read_rows(args.matrix), excludes)
    summaries = summarize_levels(rows)
    if args.copy_panels_to and not args.include_panels:
        raise SystemExit("--copy-panels-to requires --include-panels; public site builds should omit static panels.")
    panels = filter_case_paths(panel_paths(args.panels, args.output), excludes) if args.include_panels else []
    contexts = filter_case_paths(context_paths(args.contexts), excludes)
    viewers = filter_case_paths(viewer_paths(args.viewers), excludes) if args.viewers else []
    public_figures = public_figure_paths(args.public_figures)
    if args.copy_panels_to:
        panels = copy_panel_assets(panels, args.panels, args.copy_panels_to)
    if args.copy_contexts_to:
        contexts = copy_context_assets(contexts, args.contexts, args.copy_contexts_to)
    if args.copy_public_figures_to:
        public_figures = copy_panel_assets(public_figures, args.public_figures, args.copy_public_figures_to)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_html(rows, summaries, panels, contexts, args.output, viewers, annotations, public_figures),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
