from __future__ import annotations

import argparse
import csv
import html
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "results/archival_break_even/archival_break_even_matrix.csv"
DEFAULT_PANELS = ROOT / "results/break_even_review_panels"
DEFAULT_OUTPUT = ROOT / "results/break_even_report/index.html"
DEFAULT_PROFILE = ROOT / "profiles/rawtherapee/neutral-render.pp3"
DEFAULT_RENDER_INDEX = ROOT / "outputs/rawtherapee_renders/rawtherapee_render_index.csv"


@dataclass(frozen=True)
class LevelSummary:
    level: str
    rows: int
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
    size = classify_size(summary.median_size_pct)
    color = classify_delta_e(summary.p95_jxl_delta_e)
    color_ratio = classify_ratio(summary.median_color_ratio)
    structure_ratio = classify_ratio(summary.median_structure_ratio)
    verdict = classify_verdict(summary.verdicts)
    if "bad" in {size, verdict} or color == "bad":
        return "Needs review"
    if size == "good" and verdict == "good" and color in {"good", "warn"} and "bad" not in {color_ratio, structure_ratio}:
        return "Promising"
    if "risk" in {color, color_ratio, structure_ratio} or "warn" in {size, color, color_ratio, structure_ratio, verdict}:
        return "Border zone"
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


def bar(value: float | None, max_pct: float = 500.0) -> str:
    if value is None:
        return ""
    width = max(2.0, min(100.0, value / max_pct * 100.0))
    return f'<span class="bar"><span style="width:{width:.1f}%"></span></span>'


def panel_paths(panel_root: Path, output: Path) -> list[Path]:
    if not panel_root.is_dir():
        return []
    panels = [
        path
        for path in panel_root.rglob("*.png")
        if "manual" in path.name.lower()
    ]
    panels.sort(key=lambda path: (path.parent.as_posix(), level_sort(path.name), path.name))
    return panels


def relpath(path: Path, output_file: Path) -> str:
    return Path(os.path.relpath(path.resolve(), output_file.parent.resolve())).as_posix()


def esc(value: object) -> str:
    return html.escape(str(value))


def render_html(rows: list[dict[str, str]], summaries: list[LevelSummary], panels: list[Path], output: Path) -> str:
    complete = [row for row in rows if row.get("evidence_status") == "complete"]
    promising = sum(1 for row in complete if row.get("verdict") == "ps16_jxl_likely_wins")
    blocked = len(rows) - len(complete)
    by_verdict = Counter(row.get("verdict", "") for row in rows)
    baselines = summarize_baselines(rows)
    profile = read_profile_flags(DEFAULT_PROFILE)
    raw61_renders, ps16_renders = render_pair_count(DEFAULT_RENDER_INDEX)
    best_zone = [item.level for item in summaries if item.status == "Promising"]
    zone_text = ", ".join(best_zone) if best_zone else "none yet"

    level_rows = []
    for item in summaries:
        size_class = classify_size(item.median_size_pct)
        color_class = classify_delta_e(item.p95_jxl_delta_e)
        color_ratio_class = classify_ratio(item.median_color_ratio)
        structure_ratio_class = classify_ratio(item.median_structure_ratio)
        verdict_class = classify_verdict(item.verdicts)
        status_class = {
            "Promising": "good",
            "Border zone": "warn",
            "Needs review": "bad",
        }.get(item.status, "unknown")
        level_rows.append(
            f"""
            <tr>
              <td><strong>{esc(item.level)}</strong></td>
              <td class="{status_class}">{esc(item.status)}</td>
              <td class="{size_class}">{fmt(item.median_size_pct, 1, "%")}{bar(item.median_size_pct)}</td>
              <td>{fmt(item.min_size_pct, 1, "%")} - {fmt(item.max_size_pct, 1, "%")}</td>
              <td class="{color_class}">{fmt(item.p95_jxl_delta_e, 2)}</td>
              <td class="{color_ratio_class}">{fmt(item.median_color_ratio, 2)}x</td>
              <td>{fmt(item.median_jxl_structure_loss, 3)}</td>
              <td class="{structure_ratio_class}">{fmt(item.median_structure_ratio, 2)}x</td>
              <td class="{verdict_class}">{verdict_text(item.verdicts)}</td>
            </tr>
            """
        )

    baseline_rows = []
    for item in baselines:
        raw_color_class = classify_delta_e(item.raw_delta_e_stress)
        baseline_rows.append(
            f"""
            <tr>
              <td>{esc(item.scan_set)}</td>
              <td><strong>{esc(item.set_id)}</strong></td>
              <td>{fmt(item.raw_delta_e_identity, 2)}</td>
              <td class="{raw_color_class}">{fmt(item.raw_delta_e_stress, 2)}</td>
              <td>{fmt(item.raw_structure_loss, 3)}</td>
              <td>{fmt(item.worst_jxl_delta_e_stress, 2)}</td>
              <td>{fmt(item.worst_jxl_structure_loss, 3)}</td>
            </tr>
            """
        )

    image_cards = []
    for path in panels:
        name = path.name
        src = relpath(path, output)
        image_cards.append(
            f"""
            <a class="panel-card" href="{esc(src)}">
              <img src="{esc(src)}" alt="{esc(name)}">
              <span>{esc(name)}</span>
            </a>
            """
        )
    if not image_cards:
        image_cards.append('<p class="muted">No manual review panels found yet.</p>')

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
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    .questions {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .flow {{ display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr); gap: 10px; align-items: stretch; }}
    .flow-col {{ display: grid; gap: 8px; }}
    .flow-box {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; min-height: 82px; }}
    .flow-box strong {{ display: block; margin-bottom: 4px; }}
    .flow-box p {{ font-size: 13px; color: var(--muted); margin: 0; }}
    .arrow {{ display: flex; align-items: center; justify-content: center; color: var(--muted); font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); background: #f0f2f4; position: sticky; top: 0; }}
    abbr {{ text-decoration: underline dotted; cursor: help; }}
    td.good, .pill.good {{ background: var(--good-bg); color: var(--good-ink); }}
    td.warn, .pill.warn {{ background: var(--warn-bg); color: var(--warn-ink); }}
    td.risk, .pill.risk {{ background: var(--risk-bg); color: var(--risk-ink); }}
    td.bad, .pill.bad {{ background: var(--bad-bg); color: var(--bad-ink); }}
    td.unknown, .pill.unknown {{ background: var(--unknown-bg); color: var(--unknown-ink); }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; }}
    .bar {{ display: block; height: 6px; margin-top: 5px; background: #e3e7eb; border-radius: 999px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: currentColor; opacity: 0.55; }}
    .panel-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .panel-card {{ display: block; color: inherit; text-decoration: none; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .panel-card img {{ display: block; width: 100%; height: auto; background: #fff; }}
    .panel-card span {{ display: block; padding: 8px 10px; font-size: 13px; color: var(--muted); }}
    .note {{ border-left: 4px solid #6b7280; padding: 10px 12px; background: #fff; }}
    .small-table th, .small-table td {{ font-size: 13px; }}
    ul {{ margin-top: 8px; }}
    @media (max-width: 900px) {{
      .grid, .questions, .panel-grid, .flow {{ grid-template-columns: 1fr; }}
      .arrow {{ display: none; }}
      header, main {{ padding: 16px; }}
      table {{ font-size: 13px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>JPEG XL vs RAW61 Break-even Report</h1>
    <p class="muted">Local/private navigation page generated from current CSV results and review panels.</p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><h3>Rows</h3><div class="metric">{len(rows)}</div><p class="muted">break-even rows</p></div>
      <div class="card"><h3>Complete</h3><div class="metric">{len(complete)}</div><p class="muted">rows with required metrics</p></div>
      <div class="card"><h3>Promising Rows</h3><div class="metric">{promising}</div><p class="muted">PS16 JXL likely wins</p></div>
      <div class="card"><h3>Promising Levels</h3><div class="metric">{esc(zone_text)}</div><p class="muted">automatic overview only</p></div>
    </section>

    <h2>What Are We Asking?</h2>
    <section class="questions">
      <div class="card"><h3>1. Codec question</h3><p><strong>PS16 reference vs PS16 JXL.</strong> This is apples-to-apples and measures JPEG XL damage to a fixed rendered image state.</p></div>
      <div class="card"><h3>2. Archive-value question</h3><p><strong>PS16 JXL vs RAW61.</strong> This is intentionally a workflow tradeoff: more sampling plus lossy coding versus less sampling plus raw preservation.</p></div>
      <div class="card"><h3>3. Break-even question</h3><p>At what JXL distance does PS16 JXL stop carrying more useful film information than RAW61 at the same storage budget?</p></div>
      <div class="card"><h3>4. Operational question</h3><p>Can the retained files remain decodable, documented, color-managed, and practical as archive masters or secondary masters?</p></div>
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
        <div class="flow-box"><strong>ADC DNG/JXL</strong><p>Experimental branch. Useful but blocked for now by app support and DNG metadata/geometry concerns.</p></div>
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

    <h2>Level Summary</h2>
    <div class="note">
      <p><strong>What this table is for:</strong> compare JPEG XL distance levels. RAW61 baselines are moved to the next table because they do not change when the JXL distance changes.</p>
      <p><strong>Important:</strong> the colors below are diagnostic labels, not FADGI conformance claims. FADGI-style target measurements are interpretation anchors because this project compares rendered film scans and compression candidates, not calibrated capture-target conformance.</p>
    </div>
    <table>
      <thead>
        <tr>
          <th>{abbr("JXL level", "JPEG XL distance label. d030 means distance 0.30.")}</th>
          <th>{abbr("Status", "Report-level diagnostic status: size, color and verdict combined.")}</th>
          <th>{abbr("Median size vs RAW61", "Median retained JXL size as percent of paired 61 MP raw size. Below 100% is within budget.")}</th>
          <th>{abbr("Size range", "Smallest to largest size-vs-RAW61 across complete frame pairs.")}</th>
          <th>{abbr("JXL color p95", "95th percentile across frame-level JXL patch p95 DeltaE00 after hard negative-density stress. Measures codec color/tone movement.")}</th>
          <th>{abbr("Color loss ratio", "Median JXL color loss divided by RAW61 color baseline. Below 1 means JXL is closer to PS16 than RAW61 is.")}</th>
          <th>{abbr("JXL structure", "Median high-pass structure loss for JXL versus PS16. Lower means closer to PS16.")}</th>
          <th>{abbr("Structure ratio", "Median JXL structure loss divided by RAW61 structure baseline. Below 1 means JXL is structurally closer to PS16 than RAW61 is.")}</th>
          <th>{abbr("Verdicts", "Counts of conservative matrix verdicts for this level.")}</th>
        </tr>
      </thead>
      <tbody>
        {''.join(level_rows)}
      </tbody>
    </table>

    <h2>RAW61 Baseline By Frame</h2>
    <div class="note">
      <p><strong>What this table is for:</strong> show the apples-to-oranges part explicitly. RAW61 values are frame baselines: they are expected to repeat across JXL levels and should be reviewed for alignment, acutance, color profile and tone differences.</p>
    </div>
    <table class="small-table">
      <thead>
        <tr>
          <th>{abbr("Scan set", "Local private scan folder / material label.")}</th>
          <th>{abbr("Frame", "Capture set id.")}</th>
          <th>{abbr("RAW61 color", "RAW61 vs PS16 patch p95 DeltaE00 before stress.")}</th>
          <th>{abbr("RAW61 stress color", "RAW61 vs PS16 patch p95 DeltaE00 after hard negative-density transform.")}</th>
          <th>{abbr("RAW61 structure", "RAW61 high-pass structure loss against PS16 after registration.")}</th>
          <th>{abbr("Worst JXL color", "Worst JXL stress DeltaE00 across levels currently in the matrix.")}</th>
          <th>{abbr("Worst JXL structure", "Worst JXL structure loss across levels currently in the matrix.")}</th>
        </tr>
      </thead>
      <tbody>
        {''.join(baseline_rows)}
      </tbody>
    </table>

    <h2>Render/Profile Audit</h2>
    <section class="questions">
      <div class="card"><h3>Current profile</h3><p><code>{esc(DEFAULT_PROFILE.relative_to(ROOT))}</code></p><p class="muted">Render index contains {raw61_renders} RAW61 rows and {ps16_renders} PS16 rows.</p></div>
      <div class="card"><h3>Color management</h3><p>Input profile: <code>{esc(profile["input_profile"])}</code><br>Working profile: <code>{esc(profile["working_profile"])}</code><br>Output profile: <code>{esc(profile["output_profile"])}</code></p></div>
      <div class="card"><h3>White balance warning</h3><p>WB enabled: <code>{esc(profile["white_balance_enabled"])}</code><br>WB setting: <code>{esc(profile["white_balance_setting"])}</code></p><p class="muted">Camera WB can differ between ARW and PixelShift2DNG metadata, so RAW61 may render less orange even with the same profile file.</p></div>
      <div class="card"><h3>Detail handling</h3><p>RAW Bayer demosaic: <code>{esc(profile["raw_bayer_method"])}</code><br>Sharpening enabled: <code>{esc(profile["sharpening_enabled"])}</code></p><p class="muted">Apparent RAW61 sharpness can still come from demosaic/acutance, scaling and local alignment.</p></div>
    </section>

    <h2>Visual Review Panels</h2>
    <p class="muted">Click a panel to inspect it at full size. These are local/private outputs.</p>
    <section class="panel-grid">
      {''.join(image_cards)}
    </section>

    <h2>How To Interpret The Colors</h2>
    <section class="questions">
      <div class="card"><h3>Size</h3><p><span class="pill good">good</span> median candidate size at or below RAW61. <span class="pill warn">border</span> up to 115%. <span class="pill bad">bad</span> clearly over budget.</p></div>
      <div class="card"><h3>&Delta;E00</h3><p><span class="pill good">&le;1</span> very small. <span class="pill warn">&le;2</span> visible to trained review. <span class="pill risk">&le;3</span> needs caution. <span class="pill bad">&gt;3</span> large for this codec-diff use.</p></div>
      <div class="card"><h3>Ratios</h3><p><span class="pill good">&le;0.5x</span> JXL loss far below RAW61 baseline. <span class="pill warn">&le;0.8x</span> still lower. <span class="pill risk">&le;1.1x</span> near break-even. <span class="pill bad">&gt;1.1x</span> RAW61 likely wins that metric.</p></div>
      <div class="card"><h3>Diff Panels</h3><p>Bright diff pixels mean different from PS16. RAW61 diff includes sampling, scaling, alignment, acutance, and render differences. JXL diff is mostly codec error.</p></div>
    </section>

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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = read_rows(args.matrix)
    summaries = summarize_levels(rows)
    panels = panel_paths(args.panels, args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(rows, summaries, panels, args.output), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
