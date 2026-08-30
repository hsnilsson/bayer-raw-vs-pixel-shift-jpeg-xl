from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from break_even_image_tools import crop, read_rgb_image  # noqa: E402
import run_local_scan_study as local_study  # noqa: E402
from make_break_even_review_panels import (  # noqa: E402
    choose_cases,
    jxl_path,
    local_align_raw61,
    ps16_path,
    raw61_path,
    read_csv_rows,
    run_decode,
)
from run_public_latitude_stress import build_transforms  # noqa: E402


DEFAULT_MATRIX = ROOT / "results/archival_break_even/archival_break_even_matrix.csv"
DEFAULT_RENDERS_ROOT = ROOT / "outputs/rawtherapee_renders"
DEFAULT_REGISTERED_ROOT = ROOT / "outputs/registered_raw61_to_ps16"
DEFAULT_RENDERED_JXL_ROOT = ROOT / "outputs/rendered_ps16_jxl_matrix"
DEFAULT_OUTPUT = ROOT / "site/assets/review-viewers"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"
DEFAULT_LEVELS = ["d020", "d022", "d025", "d028", "d030", "d100", "d200"]
DEFAULT_CASES = [
    "fuji_679_f_ii_1983|_DSC6980",
    "kodak_gold_200_5_1997|_DSC6735",
    "konica_vx100_probable_1995|_DSC6917",
]
DEFAULT_CROP = (3182, 4782, 512, 512)
DEFAULT_CROP_NAME = "manual-01"


def find_tool(name: str, fallback: Path, explicit: Path | None = None) -> str:
    candidates = [str(explicit)] if explicit else []
    candidates.extend([name, str(fallback)])
    for candidate in candidates:
        if "\\" not in candidate and "/" not in candidate:
            found = shutil.which(candidate)
            if found:
                return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    raise SystemExit(f"Could not find {name}; pass --{name} or place it at {fallback}")


def parse_case(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError('case must be "scan set|set id"')
    return parts[0], parts[1]


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height")
    try:
        x, y, width, height = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop values must be integers") from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("crop values must be non-negative x/y and positive width/height")
    return x, y, width, height


def read_crop_plan(path: Path | None) -> dict[tuple[str, str], list[tuple[str, tuple[int, int, int, int]]]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan: dict[tuple[str, str], list[tuple[str, tuple[int, int, int, int]]]] = {}
    for item in payload.get("cases", {}).values():
        key = (str(item.get("scan_set", "")), str(item.get("set_id", "")))
        if not all(key):
            continue
        crops: list[tuple[str, tuple[int, int, int, int]]] = []
        for crop_item in item.get("crops", []):
            values = crop_item.get("crop", [])
            if len(values) != 4:
                continue
            try:
                crop_values = tuple(int(value) for value in values)
            except (TypeError, ValueError):
                continue
            if crop_values[2] <= 0 or crop_values[3] <= 0:
                continue
            name = str(crop_item.get("name") or f"manual-{len(crops) + 1:02d}")
            crops.append((name, crop_values))
        if crops:
            plan[key] = crops
    return plan


def to_display(arr: np.ndarray, max_dim: int) -> Image.Image:
    values = np.asarray(arr, dtype=np.float32)
    if values.ndim == 2:
        values = np.repeat(values[:, :, None], 3, axis=2)
    if np.issubdtype(arr.dtype, np.integer):
        values = values / float(np.iinfo(arr.dtype).max)
    low, high = np.percentile(values[:, :, :3], [0.5, 99.5])
    if high <= low:
        high = low + 1e-6
    values = np.clip((values[:, :, :3] - low) / (high - low), 0.0, 1.0)
    image = Image.fromarray(np.round(values * 255).astype(np.uint8), mode="RGB")
    if max(image.size) > max_dim:
        scale = max_dim / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    return image


def save_display(path: Path, arr: np.ndarray, max_dim: int, *, force: bool) -> None:
    if path.is_file() and not force:
        return
    to_display(arr, max_dim).save(path)


def html_page(title: str, image_names: dict[str, str], metadata: dict[str, object]) -> str:
    image_json = json.dumps(image_names, ensure_ascii=True)
    metadata_json = json.dumps(metadata, ensure_ascii=True)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | interactive review</title>
  <style>
    :root {{ color-scheme: light; --ink:#1d2329; --muted:#5f6b76; --line:#d8dee4; --bg:#f6f7f8; --panel:#fff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:14px/1.45 Arial, sans-serif; color:var(--ink); background:var(--bg); }}
    main {{ max-width:1400px; margin:0 auto; padding:22px; }}
    h1 {{ font-size:22px; margin:0 0 5px; }}
    p {{ margin:0 0 12px; }}
    .muted {{ color:var(--muted); }}
    .toolbar {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; background:var(--panel); border:1px solid var(--line); padding:10px; margin:16px 0 10px; }}
    button, select, input {{ font:inherit; }}
    button {{ border:1px solid #b9c2ca; background:#fff; color:var(--ink); padding:7px 10px; cursor:pointer; }}
    button[aria-pressed="true"] {{ background:#1d2329; color:#fff; border-color:#1d2329; }}
    label {{ display:flex; align-items:center; gap:6px; }}
    canvas {{ display:block; width:100%; height:min(72vh, 820px); min-height:360px; background:#17191b; border:1px solid #343a40; cursor:grab; touch-action:none; }}
    canvas.dragging {{ cursor:grabbing; }}
    .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:9px; color:var(--muted); }}
    .legend strong {{ color:var(--ink); }}
    .note {{ background:#fff; border-left:4px solid #6b7280; padding:9px 12px; margin-top:12px; }}
    @media (max-width:700px) {{ main {{ padding:12px; }} canvas {{ min-height:280px; height:60vh; }} .toolbar {{ align-items:flex-start; }} }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="muted">Interactive crop review. The reference is the PS16 render; the candidate can be RAW61 or a decoded PS16 JPEG XL level.</p>
  <div class="toolbar" aria-label="Review controls">
    <label>Candidate <select id="candidate"></select></label>
    <button id="toggleOverlay" aria-pressed="false">Overlay candidate on left (O)</button>
    <button id="zoomOut" title="Zoom out">-</button>
    <button id="zoomIn" title="Zoom in">+</button>
    <button id="reset">Reset view</button>
  </div>
  <canvas id="viewer"></canvas>
  <div class="legend"><span><strong>Reference:</strong> PS16 render</span><span><strong>Candidate:</strong> selected above</span><span>Press O or the button to copy the right-hand candidate over the left reference pane. Drag to pan; use the mouse wheel or buttons to zoom.</span></div>
  <div class="note"><strong>Interpretation:</strong> side-by-side is best for broad color and texture checks. The left overlay toggle is best for flicking between perfectly aligned reference/candidate detail without changing zoom or pan. The two side-by-side panes are clipped to their own halves.</div>
</main>
<script>
const files = {image_json};
const metadata = {metadata_json};
const canvas = document.getElementById('viewer');
const ctx = canvas.getContext('2d');
const select = document.getElementById('candidate');
const state = {{ mode:'side', candidate:'', zoom:1, panX:0, panY:0, dragging:false, lastX:0, lastY:0, images:{{}} }};
const candidateNames = Object.keys(files).filter((key) => key !== 'reference');
for (const key of candidateNames) {{ const option = document.createElement('option'); option.value = key; option.textContent = metadata.labels[key] || key; select.appendChild(option); }}
state.candidate = candidateNames[0] || '';
select.value = state.candidate;
const load = (key) => new Promise((resolve, reject) => {{ const image = new Image(); image.onload = () => {{ state.images[key] = image; resolve(); }}; image.onerror = reject; image.src = files[key]; }});
Promise.all(Object.keys(files).map(load)).then(() => {{ resizeCanvas(); draw(); }}).catch(() => {{ document.querySelector('.note').textContent = 'Could not load one or more review images.'; }});
function resizeCanvas() {{ const rect = canvas.getBoundingClientRect(); const ratio = window.devicePixelRatio || 1; canvas.width = Math.max(1, Math.round(rect.width * ratio)); canvas.height = Math.max(1, Math.round(rect.height * ratio)); ctx.setTransform(ratio,0,0,ratio,0,0); }}
function viewSize() {{ return {{ width:canvas.clientWidth, height:canvas.clientHeight }}; }}
function fitScale(image, width, height) {{ return Math.min(width / image.width, height / image.height); }}
function drawImageFit(image, x, y, width, height, extraZoom, clipRect) {{
  if (clipRect) {{ ctx.save(); ctx.beginPath(); ctx.rect(...clipRect); ctx.clip(); }}
  const scale = fitScale(image, width, height) * state.zoom * extraZoom; const w=image.width*scale, h=image.height*scale;
  ctx.drawImage(image, x + (width-w)/2 + state.panX, y + (height-h)/2 + state.panY, w, h);
  if (clipRect) ctx.restore();
}}
function draw() {{
  const {{width,height}} = viewSize(); ctx.clearRect(0,0,width,height); ctx.fillStyle='#17191b'; ctx.fillRect(0,0,width,height);
  const reference = state.images.reference; const candidate = state.images[state.candidate]; if (!reference || !candidate) return;
  const half = width/2;
  drawImageFit(reference,0,0,half,height,1,[0,0,half,height]);
  drawImageFit(candidate,half,0,half,height,1,[half,0,half,height]);
  if (state.mode === 'overlay') drawImageFit(candidate,0,0,half,height,1,[0,0,half,height]);
  ctx.strokeStyle='#fff'; ctx.globalAlpha=.45; ctx.beginPath(); ctx.moveTo(half,0); ctx.lineTo(half,height); ctx.stroke(); ctx.globalAlpha=1;
}}
function setMode(mode) {{ state.mode=mode; document.getElementById('toggleOverlay').setAttribute('aria-pressed', mode==='overlay'); document.getElementById('toggleOverlay').textContent=mode==='overlay' ? 'Remove left overlay (O)' : 'Overlay candidate on left (O)'; draw(); }}
function toggleOverlay() {{ setMode(state.mode === 'overlay' ? 'side' : 'overlay'); }}
function setZoom(value) {{ state.zoom=Math.max(.25,Math.min(8,value)); draw(); }}
select.addEventListener('change', () => {{ state.candidate=select.value; state.panX=0; state.panY=0; draw(); }});
document.getElementById('toggleOverlay').addEventListener('click', toggleOverlay);
document.getElementById('zoomOut').addEventListener('click', () => setZoom(state.zoom/1.35));
document.getElementById('zoomIn').addEventListener('click', () => setZoom(state.zoom*1.35));
document.getElementById('reset').addEventListener('click', () => {{ state.zoom=1; state.panX=0; state.panY=0; draw(); }});
canvas.addEventListener('wheel', (event) => {{ event.preventDefault(); setZoom(state.zoom * (event.deltaY < 0 ? 1.12 : 1/1.12)); }}, {{passive:false}});
canvas.addEventListener('pointerdown', (event) => {{ state.dragging=true; state.lastX=event.clientX; state.lastY=event.clientY; canvas.classList.add('dragging'); canvas.setPointerCapture(event.pointerId); }});
canvas.addEventListener('pointermove', (event) => {{ if (!state.dragging) return; state.panX += event.clientX-state.lastX; state.panY += event.clientY-state.lastY; state.lastX=event.clientX; state.lastY=event.clientY; draw(); }});
canvas.addEventListener('pointerup', (event) => {{ state.dragging=false; canvas.classList.remove('dragging'); canvas.releasePointerCapture(event.pointerId); }});
window.addEventListener('resize', () => {{ resizeCanvas(); draw(); }});
document.addEventListener('keydown', (event) => {{ if (event.target.matches('input,select,textarea')) return; if (event.key.toLowerCase() === 'o') toggleOverlay(); if (event.key === 'Escape') document.getElementById('reset').click(); }});
</script>
</body>
</html>
'''


def make_viewer(
    scan_set: str,
    set_id: str,
    levels: list[str],
    transform_name: str,
    crop_name: str,
    crop_spec: tuple[int, int, int, int],
    args: argparse.Namespace,
    djxl: str,
) -> Path | None:
    ref_path = ps16_path(args.renders_root, scan_set, set_id)
    raw_path = raw61_path(args.registered_root, scan_set, set_id)
    if not ref_path.is_file() or not raw_path.is_file():
        return None
    reference_full = read_rgb_image(ref_path)
    raw_full = read_rgb_image(raw_path)
    crop_text = ",".join(str(value) for value in crop_spec)
    ref_crop = crop(reference_full, crop_text)
    raw_crop = crop(raw_full, crop_text)
    aligned_raw, alignment = local_align_raw61(ref_crop, raw_crop, args.max_local_shift)
    transforms = {transform.name: transform for transform in build_transforms(ref_crop)}
    if transform_name not in transforms:
        raise SystemExit(f"Unknown transform: {transform_name}")
    transform = transforms[transform_name]
    images: dict[str, str] = {"reference": "reference.png", "ps16_lossless": "reference.png", "raw61": "raw61.png"}
    labels: dict[str, str] = {
        "reference": "PS16 reference",
        "ps16_lossless": "PS16 lossless / reference",
        "raw61": "RAW61 local aligned",
    }
    output_dir = args.output_dir / local_study.slugify(scan_set) / set_id / crop_name
    output_dir.mkdir(parents=True, exist_ok=True)
    save_display(output_dir / images["reference"], transform.apply(ref_crop), args.max_dim, force=args.force)
    save_display(output_dir / images["raw61"], transform.apply(aligned_raw), args.max_dim, force=args.force)
    with tempfile.TemporaryDirectory(prefix="break-even-viewer-") as temp_dir:
        temp_root = Path(temp_dir)
        for level in levels:
            source = jxl_path(args.rendered_jxl_root, scan_set, set_id, level)
            if not source.is_file():
                continue
            images[f"jxl_{level}"] = f"jxl_{level}.png"
            labels[f"jxl_{level}"] = f"PS16 JXL {level}"
            output = output_dir / images[f"jxl_{level}"]
            if output.is_file() and not args.force:
                continue
            decoded = temp_root / level / "ps16_candidate.ppm"
            run_decode(djxl, source, decoded)
            candidate = crop(read_rgb_image(decoded), crop_text)
            save_display(output, transform.apply(candidate), args.max_dim, force=args.force)
    if len(images) < 3:
        return None
    metadata = {
        "labels": labels,
        "scan_set": scan_set,
        "set_id": set_id,
        "crop_name": crop_name,
        "transform": transform_name,
        "crop": list(crop_spec),
        "local_raw61_alignment": {
            "shift_x_px": alignment.shift_x_px,
            "shift_y_px": alignment.shift_y_px,
            "confidence": alignment.confidence,
            "applied": alignment.applied,
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    title = f"{scan_set} / {set_id} / {crop_name} / {transform_name}"
    (output_dir / "index.html").write_text(html_page(title, images, metadata), encoding="utf-8")
    return output_dir / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create small static interactive review viewers for selected break-even crops.")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--renders-root", type=Path, default=DEFAULT_RENDERS_ROOT)
    parser.add_argument("--registered-root", type=Path, default=DEFAULT_REGISTERED_ROOT)
    parser.add_argument("--rendered-jxl-root", type=Path, default=DEFAULT_RENDERED_JXL_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--djxl", type=Path)
    parser.add_argument("--case", action="append", type=parse_case)
    parser.add_argument("--all-complete", action="store_true", help="make viewers for all complete cases in the matrix")
    parser.add_argument("--case-limit", type=int, default=999)
    parser.add_argument("--level", action="append", default=None)
    parser.add_argument("--transform", default="identity")
    parser.add_argument("--crop", type=parse_crop, default=DEFAULT_CROP)
    parser.add_argument("--crop-plan", type=Path, help="JSON crop plan produced by read_crop_selection_guides.py or serve_crop_selection.py.")
    parser.add_argument("--max-dim", type=int, default=1024)
    parser.add_argument("--max-local-shift", type=float, default=32.0)
    parser.add_argument("--jobs", type=int, default=1, help="number of crop viewers to build in parallel")
    parser.add_argument("--force", action="store_true", help="rewrite existing viewer images")
    args = parser.parse_args()
    if args.max_dim <= 0:
        raise SystemExit("--max-dim must be positive")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    if args.case:
        cases = args.case
    elif args.all_complete:
        cases = [(case.scan_set, case.set_id) for case in choose_cases(read_csv_rows(args.matrix), args.case_limit)]
    else:
        cases = [parse_case(value) for value in DEFAULT_CASES]
    levels = args.level or DEFAULT_LEVELS
    crop_plan = read_crop_plan(args.crop_plan)
    djxl = find_tool("djxl", DEFAULT_DJXL, args.djxl)
    tasks = []
    for scan_set, set_id in cases:
        crop_specs = crop_plan.get((scan_set, set_id))
        if not crop_specs and not crop_plan:
            crop_specs = [(DEFAULT_CROP_NAME, args.crop)]
        for crop_name, crop_spec in crop_specs or []:
            tasks.append((scan_set, set_id, crop_name, crop_spec))
    written = []
    if args.jobs == 1 or len(tasks) <= 1:
        for scan_set, set_id, crop_name, crop_spec in tasks:
            result = make_viewer(scan_set, set_id, levels, args.transform, crop_name, crop_spec, args, djxl)
            if result:
                written.append(str(result))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [
                executor.submit(make_viewer, scan_set, set_id, levels, args.transform, crop_name, crop_spec, args, djxl)
                for scan_set, set_id, crop_name, crop_spec in tasks
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    written.append(str(result))
    written.sort()
    print(f"Wrote {len(written)} interactive viewer(s)")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
