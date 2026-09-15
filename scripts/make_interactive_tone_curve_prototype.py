from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from break_even_image_tools import crop, read_rgb_image  # noqa: E402


DEFAULT_OUTPUT = ROOT / "work/tone-curve-prototype"
SCOPE_NOTE = (
    "This tests editing latitude inside the fixed rendered RGB chain. "
    "It does not measure all latitude available from developing the original raw files."
)


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height")
    try:
        x, y, width, height = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop values must be integers") from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("crop needs non-negative x/y and positive width/height")
    return x, y, width, height


def normalized_rgb(arr: np.ndarray) -> np.ndarray:
    values = np.asarray(arr)
    if values.ndim == 2:
        values = np.repeat(values[:, :, None], 3, axis=2)
    if values.ndim != 3 or values.shape[2] < 3:
        raise ValueError(f"expected an RGB array, got {values.shape}")
    values = values[:, :, :3]
    if np.issubdtype(values.dtype, np.integer):
        maximum = float(np.iinfo(values.dtype).max)
        return values.astype(np.float32) / maximum
    result = values.astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("floating-point RGB input contains non-finite samples")
    if float(result.min()) < 0.0 or float(result.max()) > 1.0:
        raise ValueError("floating-point RGB input must be normalized to 0..1")
    return result


def source_precision_bits(arr: np.ndarray) -> int:
    if np.issubdtype(arr.dtype, np.integer):
        return int(np.iinfo(arr.dtype).bits)
    return int(np.finfo(arr.dtype).bits)


def encode_rgb16le(arr: np.ndarray) -> bytes:
    values = normalized_rgb(arr)
    quantized = np.round(np.clip(values, 0.0, 1.0) * 65535.0).astype("<u2")
    return quantized.tobytes(order="C")


def reference_display_range(arr: np.ndarray) -> tuple[float, float]:
    values = normalized_rgb(arr)
    low, high = (float(value) for value in np.percentile(values, [0.5, 99.5]))
    return low, max(high, low + 1e-6)


def build_metadata(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    title: str,
    reference_label: str,
    candidate_label: str,
    crop_spec: tuple[int, int, int, int],
) -> dict[str, object]:
    if reference.shape != candidate.shape:
        raise ValueError(f"reference/candidate crop shapes differ: {reference.shape} != {candidate.shape}")
    low, high = reference_display_range(reference)
    height, width = reference.shape[:2]
    return {
        "schema_version": 1,
        "title": title,
        "reference_label": reference_label,
        "candidate_label": candidate_label,
        "width": width,
        "height": height,
        "channels": 3,
        "storage": "uint16le-interleaved-rgb",
        "stored_precision_bits": 16,
        "reference_source_dtype": str(reference.dtype),
        "candidate_source_dtype": str(candidate.dtype),
        "reference_source_precision_bits": source_precision_bits(reference),
        "candidate_source_precision_bits": source_precision_bits(candidate),
        "reference_file": "reference.rgb16le",
        "candidate_file": "candidate.rgb16le",
        "crop": list(crop_spec),
        "initial_black_point": low,
        "initial_white_point": high,
        "initial_range_method": "reference RGB p0.5-p99.5; applied in the browser before 8-bit display quantization",
        "scope_note": SCOPE_NOTE,
    }


def write_prototype(
    reference: np.ndarray,
    candidate: np.ndarray,
    output_dir: Path,
    *,
    title: str,
    reference_label: str,
    candidate_label: str,
    crop_spec: tuple[int, int, int, int],
) -> Path:
    metadata = build_metadata(
        reference,
        candidate,
        title=title,
        reference_label=reference_label,
        candidate_label=candidate_label,
        crop_spec=crop_spec,
    )
    if min(
        int(metadata["reference_source_precision_bits"]),
        int(metadata["candidate_source_precision_bits"]),
    ) <= 8:
        raise ValueError(
            "the tone-curve prototype requires source samples above 8-bit; "
            "regenerate or decode the fixed rendered RGB pair at 16-bit precision"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reference.rgb16le").write_bytes(encode_rgb16le(reference))
    (output_dir / "candidate.rgb16le").write_bytes(encode_rgb16le(candidate))
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    page = HTML_TEMPLATE.replace(
        "__TONE_CURVE_METADATA__",
        json.dumps(metadata, ensure_ascii=True).replace("<", "\\u003c"),
    )
    index_path = output_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    return index_path


def read_crop(path: Path, crop_spec: tuple[int, int, int, int]) -> np.ndarray:
    values = read_rgb_image(path)
    return np.asarray(crop(values, ",".join(str(value) for value in crop_spec)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build one local 16-bit histogram and tone-curve prototype from a rendered RGB crop pair."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--crop", type=parse_crop, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--title", default="Rendered RGB latitude prototype")
    parser.add_argument("--reference-label", default="PS16 reference")
    parser.add_argument("--candidate-label", default="PS16 JPEG XL candidate")
    args = parser.parse_args()

    for label, path in (("reference", args.reference), ("candidate", args.candidate)):
        if not path.is_file():
            raise SystemExit(f"Missing {label} image: {path}")
    reference = read_crop(args.reference, args.crop)
    candidate = read_crop(args.candidate, args.crop)
    try:
        index_path = write_prototype(
            reference,
            candidate,
            args.output_dir,
            title=args.title,
            reference_label=args.reference_label,
            candidate_label=args.candidate_label,
            crop_spec=args.crop,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(index_path)
    return 0


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rendered RGB latitude prototype</title>
  <style>
    :root { color-scheme: dark; --bg:#0c1014; --panel:#151b21; --panel-2:#1c242c; --line:#34414d; --ink:#edf3f8; --muted:#aab8c4; --cyan:#55d6e8; --amber:#ffbd59; --danger:#ff6b73; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 Arial, Helvetica, sans-serif; }
    main { width:min(1500px, 100%); margin:0 auto; padding:20px; }
    h1 { margin:0; font-size:clamp(1.35rem, 2.4vw, 2rem); }
    p { margin:.4rem 0 0; }
    .muted { color:var(--muted); }
    .scope { margin:14px 0; border-left:4px solid var(--amber); background:#2b2418; padding:10px 12px; }
    .workspace { display:grid; grid-template-columns:minmax(270px, 340px) minmax(0, 1fr); gap:14px; align-items:start; }
    .panel { border:1px solid var(--line); border-radius:10px; background:var(--panel); overflow:hidden; }
    .controls { display:grid; gap:14px; padding:14px; }
    .control { display:grid; grid-template-columns:1fr auto; gap:5px 10px; align-items:center; }
    .control output { color:var(--cyan); font:700 .9rem/1 ui-monospace, SFMono-Regular, Consolas, monospace; }
    .control input { grid-column:1 / -1; width:100%; accent-color:var(--cyan); }
    button { border:1px solid var(--line); border-radius:7px; background:var(--panel-2); color:var(--ink); padding:8px 11px; font:inherit; cursor:pointer; }
    button:hover, button:focus-visible { border-color:var(--cyan); }
    .curve-wrap { padding:0 14px 14px; }
    .curve-wrap h2, .histogram-wrap h2 { margin:0 0 7px; font-size:1rem; }
    #curveCanvas { display:block; width:100%; aspect-ratio:1; min-height:250px; border:1px solid var(--line); background:#0b0f13; touch-action:none; cursor:crosshair; }
    .stage { display:grid; gap:14px; min-width:0; }
    .pair { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1px; background:var(--line); }
    figure { margin:0; min-width:0; background:#090c0f; }
    figure canvas { display:block; width:100%; height:auto; image-rendering:auto; }
    figcaption { padding:8px 10px; background:var(--panel); color:var(--muted); font-size:.875rem; }
    .histogram-wrap { padding:12px; }
    #histogramCanvas { display:block; width:100%; height:190px; border:1px solid var(--line); background:#0b0f13; }
    .legend { display:flex; flex-wrap:wrap; gap:12px; margin-top:8px; color:var(--muted); font-size:.875rem; }
    .key::before { content:""; display:inline-block; width:18px; height:3px; margin:0 6px 3px 0; background:currentColor; }
    .reference-key { color:var(--cyan); }
    .candidate-key { color:var(--amber); }
    .clipping { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; margin-top:10px; }
    .clip-card { border:1px solid var(--line); background:var(--panel-2); padding:9px 10px; border-radius:7px; }
    .clip-card strong { display:block; margin-bottom:3px; }
    .clip-values { display:flex; gap:12px; color:var(--muted); font: .85rem/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; }
    .clip-values .active { color:var(--danger); font-weight:700; }
    .status { min-height:1.5em; margin-top:8px; color:var(--muted); }
    @media (max-width:900px) { .workspace { grid-template-columns:1fr; } .controls-panel { display:grid; grid-template-columns:minmax(250px, 1fr) minmax(250px, 1fr); } .curve-wrap { padding-top:14px; } }
    @media (max-width:620px) { main { padding:12px; } .pair, .clipping, .controls-panel { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p class="muted">One reference/candidate crop pair. Both sides receive exactly the same adjustment before the browser creates an 8-bit display image.</p>
  <div class="scope"><strong>Scope:</strong> <span id="scope"></span></div>
  <div class="workspace">
    <aside class="panel controls-panel">
      <div class="controls" aria-label="Shared tone controls">
        <div class="control"><label for="exposure">Display exposure</label><output id="exposureValue"></output><input id="exposure" type="range" min="-4" max="4" step="0.1" value="0"></div>
        <div class="control"><label for="blackPoint">Black point</label><output id="blackValue"></output><input id="blackPoint" type="range" min="0" max="1" step="0.0001"></div>
        <div class="control"><label for="whitePoint">White point</label><output id="whiteValue"></output><input id="whitePoint" type="range" min="0" max="1" step="0.0001"></div>
        <div class="control"><label for="curve25">Quarter-tone output</label><output id="curve25Value"></output><input id="curve25" type="range" min="0" max="1" step="0.001" value="0.25"></div>
        <div class="control"><label for="curve50">Midtone output</label><output id="curve50Value"></output><input id="curve50" type="range" min="0" max="1" step="0.001" value="0.5"></div>
        <div class="control"><label for="curve75">Three-quarter-tone output</label><output id="curve75Value"></output><input id="curve75" type="range" min="0" max="1" step="0.001" value="0.75"></div>
        <button type="button" id="reset">Reset shared adjustment</button>
        <p class="muted">Drag the three cyan curve points vertically. The curve is monotonic and is applied channel by channel to both images.</p>
      </div>
      <div class="curve-wrap">
        <h2>Shared tone curve</h2>
        <canvas id="curveCanvas" width="320" height="320" aria-label="Editable shared tone curve"></canvas>
      </div>
    </aside>
    <section class="stage">
      <div class="panel pair">
        <figure><canvas id="referenceCanvas"></canvas><figcaption id="referenceLabel"></figcaption></figure>
        <figure><canvas id="candidateCanvas"></canvas><figcaption id="candidateLabel"></figcaption></figure>
      </div>
      <div class="panel histogram-wrap">
        <h2>Adjusted luminance histogram</h2>
        <canvas id="histogramCanvas" width="900" height="190"></canvas>
        <div class="legend"><span class="key reference-key" id="referenceLegend"></span><span class="key candidate-key" id="candidateLegend"></span><span>Clipping means at least one RGB channel reaches an endpoint.</span></div>
        <div class="clipping">
          <div class="clip-card"><strong id="referenceClipLabel"></strong><div class="clip-values"><span id="referenceBlack"></span><span id="referenceWhite"></span></div></div>
          <div class="clip-card"><strong id="candidateClipLabel"></strong><div class="clip-values"><span id="candidateBlack"></span><span id="candidateWhite"></span></div></div>
        </div>
        <div class="status" id="status" aria-live="polite">Loading 16-bit crop data…</div>
      </div>
    </section>
  </div>
</main>
<script type="application/json" id="toneCurveData">__TONE_CURVE_METADATA__</script>
<script>
(() => {
  const metadata = JSON.parse(document.getElementById("toneCurveData").textContent);
  const $ = (id) => document.getElementById(id);
  const exposure = $("exposure");
  const blackPoint = $("blackPoint");
  const whitePoint = $("whitePoint");
  const curveInputs = [$("curve25"), $("curve50"), $("curve75")];
  const curveCanvas = $("curveCanvas");
  const curveContext = curveCanvas.getContext("2d");
  const histogramCanvas = $("histogramCanvas");
  const histogramContext = histogramCanvas.getContext("2d");
  const referenceCanvas = $("referenceCanvas");
  const candidateCanvas = $("candidateCanvas");
  const curvePoints = [{x:0,y:0}, {x:.25,y:.25}, {x:.5,y:.5}, {x:.75,y:.75}, {x:1,y:1}];
  let reference = null;
  let candidate = null;
  let draggingPoint = -1;
  let framePending = false;

  document.title = `${metadata.title} | interactive review`;
  $("title").textContent = metadata.title;
  $("scope").textContent = metadata.scope_note;
  for (const id of ["referenceLabel", "referenceLegend", "referenceClipLabel"]) $(id).textContent = metadata.reference_label;
  for (const id of ["candidateLabel", "candidateLegend", "candidateClipLabel"]) $(id).textContent = metadata.candidate_label;
  blackPoint.value = metadata.initial_black_point;
  whitePoint.value = metadata.initial_white_point;

  function curveValue(input) {
    const value = Math.max(0, Math.min(1, input));
    const segment = Math.min(curvePoints.length - 2, Math.floor(value * (curvePoints.length - 1)));
    const left = curvePoints[segment];
    const right = curvePoints[segment + 1];
    const mix = (value - left.x) / (right.x - left.x);
    return left.y + (right.y - left.y) * mix;
  }

  function transformSample(sample, gain, black, white) {
    const windowed = (sample * gain - black) / Math.max(1e-6, white - black);
    return { unclipped:windowed, value:curveValue(windowed) };
  }

  function renderImage(source, target) {
    const width = metadata.width;
    const height = metadata.height;
    target.width = width;
    target.height = height;
    const context = target.getContext("2d", {alpha:false});
    const image = context.createImageData(width, height);
    const bins = new Uint32Array(256);
    const gain = Math.pow(2, Number(exposure.value));
    const black = Number(blackPoint.value);
    const white = Number(whitePoint.value);
    let blackClipped = 0;
    let whiteClipped = 0;
    for (let pixel = 0, inputIndex = 0, outputIndex = 0; pixel < width * height; pixel++, outputIndex += 4) {
      let minimum = Infinity;
      let maximum = -Infinity;
      const channels = [0, 0, 0];
      for (let channel = 0; channel < 3; channel++, inputIndex++) {
        const transformed = transformSample(source[inputIndex] / 65535, gain, black, white);
        minimum = Math.min(minimum, transformed.unclipped);
        maximum = Math.max(maximum, transformed.unclipped);
        channels[channel] = transformed.value;
        image.data[outputIndex + channel] = Math.round(transformed.value * 255);
      }
      image.data[outputIndex + 3] = 255;
      if (minimum <= 0) blackClipped++;
      if (maximum >= 1) whiteClipped++;
      const luminance = .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
      bins[Math.max(0, Math.min(255, Math.round(luminance * 255)))]++;
    }
    context.putImageData(image, 0, 0);
    return {bins, blackClipped, whiteClipped, pixels:width * height};
  }

  function drawHistogram(referenceStats, candidateStats) {
    const width = histogramCanvas.width;
    const height = histogramCanvas.height;
    histogramContext.clearRect(0, 0, width, height);
    histogramContext.fillStyle = "#0b0f13";
    histogramContext.fillRect(0, 0, width, height);
    histogramContext.strokeStyle = "#26313a";
    histogramContext.beginPath();
    for (let x = 0; x <= 4; x++) { const px = x * width / 4; histogramContext.moveTo(px, 0); histogramContext.lineTo(px, height); }
    histogramContext.stroke();
    const peak = Math.max(1, ...referenceStats.bins, ...candidateStats.bins);
    const drawBins = (bins, color) => {
      histogramContext.strokeStyle = color;
      histogramContext.lineWidth = 1.7;
      histogramContext.beginPath();
      bins.forEach((count, index) => {
        const x = index / 255 * width;
        const y = height - Math.log1p(count) / Math.log1p(peak) * (height - 5);
        if (index === 0) histogramContext.moveTo(x, y); else histogramContext.lineTo(x, y);
      });
      histogramContext.stroke();
    };
    drawBins(referenceStats.bins, "#55d6e8");
    drawBins(candidateStats.bins, "#ffbd59");
  }

  function setClipping(prefix, stats) {
    const black = 100 * stats.blackClipped / stats.pixels;
    const white = 100 * stats.whiteClipped / stats.pixels;
    const blackNode = $(`${prefix}Black`);
    const whiteNode = $(`${prefix}White`);
    blackNode.textContent = `black ${black.toFixed(2)}%`;
    whiteNode.textContent = `white ${white.toFixed(2)}%`;
    blackNode.classList.toggle("active", black > 0);
    whiteNode.classList.toggle("active", white > 0);
  }

  function drawCurve() {
    const width = curveCanvas.width;
    const height = curveCanvas.height;
    curveContext.clearRect(0, 0, width, height);
    curveContext.fillStyle = "#0b0f13";
    curveContext.fillRect(0, 0, width, height);
    curveContext.strokeStyle = "#26313a";
    curveContext.lineWidth = 1;
    for (let step = 0; step <= 4; step++) {
      const position = step * width / 4;
      curveContext.beginPath(); curveContext.moveTo(position, 0); curveContext.lineTo(position, height); curveContext.stroke();
      curveContext.beginPath(); curveContext.moveTo(0, position); curveContext.lineTo(width, position); curveContext.stroke();
    }
    curveContext.strokeStyle = "#55d6e8";
    curveContext.lineWidth = 2.5;
    curveContext.beginPath();
    curvePoints.forEach((point, index) => {
      const x = point.x * width;
      const y = (1 - point.y) * height;
      if (index === 0) curveContext.moveTo(x, y); else curveContext.lineTo(x, y);
    });
    curveContext.stroke();
    curvePoints.slice(1, -1).forEach((point) => {
      curveContext.beginPath();
      curveContext.arc(point.x * width, (1 - point.y) * height, 7, 0, Math.PI * 2);
      curveContext.fillStyle = "#55d6e8";
      curveContext.fill();
      curveContext.strokeStyle = "#071013";
      curveContext.stroke();
    });
  }

  function updateOutputs() {
    $("exposureValue").textContent = `${Number(exposure.value).toFixed(1)} EV`;
    $("blackValue").textContent = Number(blackPoint.value).toFixed(4);
    $("whiteValue").textContent = Number(whitePoint.value).toFixed(4);
    curveInputs.forEach((input, index) => { $(`curve${(index + 1) * 25}Value`).textContent = Number(input.value).toFixed(3); });
  }

  function setCurvePoint(index, value) {
    const low = curvePoints[index - 1].y;
    const high = curvePoints[index + 1].y;
    curvePoints[index].y = Math.max(low, Math.min(high, value));
    curveInputs[index - 1].value = curvePoints[index].y;
  }

  function render() {
    framePending = false;
    updateOutputs();
    drawCurve();
    if (!reference || !candidate) return;
    if (Number(blackPoint.value) >= Number(whitePoint.value) - .0001) {
      $("status").textContent = "Black point must stay below white point.";
      return;
    }
    const referenceStats = renderImage(reference, referenceCanvas);
    const candidateStats = renderImage(candidate, candidateCanvas);
    drawHistogram(referenceStats, candidateStats);
    setClipping("reference", referenceStats);
    setClipping("candidate", candidateStats);
    $("status").textContent = `Source buffers: 16-bit RGB; crop ${metadata.crop.join(",")}; display quantization happens only after the shared adjustment.`;
  }

  function scheduleRender() {
    if (framePending) return;
    framePending = true;
    requestAnimationFrame(render);
  }

  function curvePointAt(event) {
    const rect = curveCanvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = 1 - (event.clientY - rect.top) / rect.height;
    let best = -1;
    let distance = .07;
    for (let index = 1; index < curvePoints.length - 1; index++) {
      const candidateDistance = Math.hypot(x - curvePoints[index].x, y - curvePoints[index].y);
      if (candidateDistance < distance) { best = index; distance = candidateDistance; }
    }
    return {index:best, y};
  }

  curveCanvas.addEventListener("pointerdown", (event) => {
    const hit = curvePointAt(event);
    if (hit.index < 0) return;
    draggingPoint = hit.index;
    curveCanvas.setPointerCapture(event.pointerId);
  });
  curveCanvas.addEventListener("pointermove", (event) => {
    if (draggingPoint < 0) return;
    const hit = curvePointAt(event);
    setCurvePoint(draggingPoint, hit.y);
    scheduleRender();
  });
  curveCanvas.addEventListener("pointerup", (event) => {
    draggingPoint = -1;
    if (curveCanvas.hasPointerCapture(event.pointerId)) curveCanvas.releasePointerCapture(event.pointerId);
  });
  curveCanvas.addEventListener("pointercancel", () => { draggingPoint = -1; });

  for (const input of [exposure, blackPoint, whitePoint]) input.addEventListener("input", scheduleRender);
  curveInputs.forEach((input, index) => {
    input.addEventListener("input", () => { setCurvePoint(index + 1, Number(input.value)); scheduleRender(); });
  });
  $("reset").addEventListener("click", () => {
    exposure.value = 0;
    blackPoint.value = metadata.initial_black_point;
    whitePoint.value = metadata.initial_white_point;
    curvePoints.forEach((point) => { point.y = point.x; });
    curveInputs.forEach((input, index) => { input.value = curvePoints[index + 1].y; });
    scheduleRender();
  });

  async function loadRgb16(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    const buffer = await response.arrayBuffer();
    const expectedBytes = metadata.width * metadata.height * metadata.channels * 2;
    if (buffer.byteLength !== expectedBytes) throw new Error(`${path}: expected ${expectedBytes} bytes, got ${buffer.byteLength}`);
    return new Uint16Array(buffer);
  }

  updateOutputs();
  drawCurve();
  Promise.all([loadRgb16(metadata.reference_file), loadRgb16(metadata.candidate_file)])
    .then((images) => { [reference, candidate] = images; render(); })
    .catch((error) => { $("status").textContent = `Could not load the 16-bit pair: ${error.message}. Serve this directory over HTTP rather than opening index.html as a file.`; });
})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(main())
