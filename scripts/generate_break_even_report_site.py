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


@dataclass(frozen=True)
class LevelSummary:
    level: str
    rows: int
    median_size_pct: float | None
    min_size_pct: float | None
    max_size_pct: float | None
    max_jxl_delta_e: float | None
    median_raw_delta_e: float | None
    max_jxl_structure_loss: float | None
    median_raw_structure_loss: float | None
    verdicts: Counter[str]
    status: str


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
    color = classify_delta_e(summary.max_jxl_delta_e)
    verdict = classify_verdict(summary.verdicts)
    if "bad" in {size, verdict} or color == "bad":
        return "Needs review"
    if size == "good" and verdict == "good" and color in {"good", "warn"}:
        return "Promising"
    if "risk" in {color} or "warn" in {size, color, verdict}:
        return "Border zone"
    return "Incomplete"


def summarize_levels(rows: list[dict[str, str]]) -> list[LevelSummary]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("evidence_status") == "complete":
            grouped[row.get("level", "")].append(row)
    summaries: list[LevelSummary] = []
    for level, items in grouped.items():
        verdicts = Counter(row.get("verdict", "") for row in items)
        summary = LevelSummary(
            level=level,
            rows=len(items),
            median_size_pct=median(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            min_size_pct=min_value(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            max_size_pct=max_value(parse_float(row.get("size_vs_raw61_pct")) for row in items),
            max_jxl_delta_e=max_value(parse_float(row.get("color_delta_e00_p95_stress")) for row in items),
            median_raw_delta_e=median(parse_float(row.get("raw61_color_delta_e00_p95_stress")) for row in items),
            max_jxl_structure_loss=max_value(parse_float(row.get("jxl_structure_loss")) for row in items),
            median_raw_structure_loss=median(parse_float(row.get("raw61_structure_loss")) for row in items),
            verdicts=verdicts,
            status="",
        )
        summaries.append(
            LevelSummary(
                **{**summary.__dict__, "status": status_for(summary)}
            )
        )
    return sorted(summaries, key=lambda item: level_sort(item.level))


def verdict_text(counter: Counter[str]) -> str:
    return ", ".join(f"{html.escape(key)}: {value}" for key, value in sorted(counter.items())) or "-"


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
    best_zone = [item.level for item in summaries if item.status == "Promising"]
    zone_text = ", ".join(best_zone) if best_zone else "none yet"

    level_rows = []
    for item in summaries:
        size_class = classify_size(item.median_size_pct)
        color_class = classify_delta_e(item.max_jxl_delta_e)
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
              <td class="{color_class}">{fmt(item.max_jxl_delta_e, 2)}</td>
              <td>{fmt(item.median_raw_delta_e, 2)}</td>
              <td>{fmt(item.max_jxl_structure_loss, 3)}</td>
              <td>{fmt(item.median_raw_structure_loss, 3)}</td>
              <td class="{verdict_class}">{verdict_text(item.verdicts)}</td>
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
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); background: #f0f2f4; position: sticky; top: 0; }}
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
    ul {{ margin-top: 8px; }}
    @media (max-width: 900px) {{
      .grid, .questions, .panel-grid {{ grid-template-columns: 1fr; }}
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

    <h2>Level Summary</h2>
    <div class="note">
      <p><strong>Important:</strong> the colors below are diagnostic labels, not FADGI conformance claims. FADGI-style target measurements are used here as interpretation anchors because this project is comparing rendered film scans and compression candidates, not measuring a calibrated capture target in the normal FADGI workflow.</p>
    </div>
    <table>
      <thead>
        <tr>
          <th>Level</th>
          <th>Status</th>
          <th>Median size vs RAW61</th>
          <th>Size range</th>
          <th>Max JXL stress ΔE00 p95</th>
          <th>Median RAW61 stress ΔE00 p95</th>
          <th>Max JXL structure loss</th>
          <th>Median RAW61 structure loss</th>
          <th>Verdicts</th>
        </tr>
      </thead>
      <tbody>
        {''.join(level_rows)}
      </tbody>
    </table>

    <h2>Visual Review Panels</h2>
    <p class="muted">Click a panel to inspect it at full size. These are local/private outputs.</p>
    <section class="panel-grid">
      {''.join(image_cards)}
    </section>

    <h2>How To Interpret The Colors</h2>
    <section class="questions">
      <div class="card"><h3>Size</h3><p><span class="pill good">good</span> median candidate size at or below RAW61. <span class="pill warn">border</span> up to 115%. <span class="pill bad">bad</span> clearly over budget.</p></div>
      <div class="card"><h3>ΔE00</h3><p><span class="pill good">≤1</span> very small. <span class="pill warn">≤2</span> visible to trained review. <span class="pill risk">≤3</span> needs caution. <span class="pill bad">&gt;3</span> large for this codec-diff use.</p></div>
      <div class="card"><h3>Structure</h3><p>Lower structure loss means closer to PS16 high-pass detail. This is a diagnostic metric and must be checked with crops.</p></div>
      <div class="card"><h3>Diff Panels</h3><p>Bright diff pixels mean different from PS16. RAW61 diff includes sampling, scaling, alignment, acutance, and render differences. JXL diff is mostly codec error.</p></div>
    </section>

    <h2>FADGI Context</h2>
    <div class="card">
      <p>Useful established metrics include CIEDE2000 color accuracy, tone response, white balance error, color-channel misregistration, SFR/sampling efficiency, sharpening, and noise. The relevant lesson for this project is not that our film-crop rows can claim FADGI stars, but that a credible imaging study should separate color, tone, registration, detail, sharpening, and noise instead of relying on PSNR or a single diff image.</p>
      <ul>
        <li>Official FADGI 2023 guidelines describe the still-image conformance system and its target/software basis.</li>
        <li>FADGI/related practice commonly uses ΔE00 for color accuracy; strict published discussions cite average ΔE00 around 2 for highest-level color profiling, while older/practical references often discuss average 3 and maximum 6 as useful limits.</li>
        <li>NARA permanent-record rules expose related concrete thresholds: average color accuracy &lt;3.5 ΔE00, 90th percentile &lt;8.75, color-channel misregistration &lt;0.5 px, sharpening max modulation &lt;1.1, and noise upper limit &lt;2 L* std dev for the listed record category.</li>
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
