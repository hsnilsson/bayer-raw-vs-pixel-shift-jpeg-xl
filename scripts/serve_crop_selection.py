from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GUIDES = ROOT / "results/break_even_crop_guides"
DEFAULT_OUTPUT = DEFAULT_GUIDES / "crop_plan.json"
MARKER_RGB = [255, 0, 255]


@dataclass(frozen=True)
class Guide:
    key: str
    scan_set: str
    set_id: str
    image_path: Path
    metadata_path: Path
    display_width: int
    display_height: int
    source_width: int
    source_height: int
    offset_x: int
    offset_y: int

    def public_dict(self, index: int) -> dict[str, Any]:
        return {
            "key": self.key,
            "scan_set": self.scan_set,
            "set_id": self.set_id,
            "image_url": f"/guide/{index}",
            "display_width": self.display_width,
            "display_height": self.display_height,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "image_offset": [self.offset_x, self.offset_y],
        }


def load_guides(guides_root: Path) -> list[Guide]:
    guides: list[Guide] = []
    for metadata_path in sorted(guides_root.rglob("ps16_guide.json")):
        image_path = metadata_path.with_suffix(".png")
        if not image_path.is_file():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        scan_set = str(metadata["scan_set"])
        set_id = str(metadata["set_id"])
        offset = metadata.get("image_offset", [0, 0])
        guides.append(
            Guide(
                key=f"{scan_set}|{set_id}",
                scan_set=scan_set,
                set_id=set_id,
                image_path=image_path,
                metadata_path=metadata_path,
                display_width=int(metadata["display_width"]),
                display_height=int(metadata["display_height"]),
                source_width=int(metadata["source_width"]),
                source_height=int(metadata["source_height"]),
                offset_x=int(offset[0]),
                offset_y=int(offset[1]),
            )
        )
    return guides


def load_existing_markers(output: Path, guides: list[Guide]) -> tuple[int, dict[str, list[list[int]]]]:
    markers = {guide.key: [] for guide in guides}
    crop_size = 768
    if not output.is_file():
        return crop_size, markers
    payload = json.loads(output.read_text(encoding="utf-8"))
    crop_size = int(payload.get("crop_size", crop_size))
    for key, item in payload.get("cases", {}).items():
        if key not in markers:
            continue
        for crop in item.get("crops", []):
            point = crop.get("marker_display")
            if isinstance(point, list) and len(point) == 2:
                markers[key].append([int(point[0]), int(point[1])])
    return crop_size, markers


def crop_from_marker(guide: Guide, marker: list[int], crop_size: int) -> list[int]:
    display_x, display_y = marker
    source_x = round(display_x / guide.display_width * guide.source_width)
    source_y = round(display_y / guide.display_height * guide.source_height)
    size = min(crop_size, guide.source_width, guide.source_height)
    left = min(max(source_x - size // 2, 0), max(guide.source_width - size, 0))
    top = min(max(source_y - size // 2, 0), max(guide.source_height - size, 0))
    return [left, top, size, size]


def build_crop_plan(guides: list[Guide], markers: dict[str, list[list[int]]], crop_size: int) -> dict[str, Any]:
    if crop_size <= 0:
        raise ValueError("crop_size must be positive")
    cases: dict[str, Any] = {}
    for guide in guides:
        crops = []
        for index, marker in enumerate(markers.get(guide.key, []), 1):
            if len(marker) != 2:
                raise ValueError(f"Invalid marker for {guide.key}")
            x, y = int(marker[0]), int(marker[1])
            if not (0 <= x <= guide.display_width and 0 <= y <= guide.display_height):
                raise ValueError(f"Marker outside image for {guide.key}: {x},{y}")
            point = [x, y]
            crops.append(
                {
                    "name": f"manual-{index:02d}",
                    "crop": crop_from_marker(guide, point, crop_size),
                    "marker_display": point,
                }
            )
        cases[guide.key] = {
            "scan_set": guide.scan_set,
            "set_id": guide.set_id,
            "guide": str(guide.image_path.relative_to(ROOT)).replace("\\", "/"),
            "crops": crops,
        }
    return {"marker_rgb": MARKER_RGB, "crop_size": crop_size, "cases": cases}


def save_crop_plan(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, output)


HTML = r'''<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Crop marker</title>
  <style>
    :root { color-scheme: dark; --bg:#111315; --panel:#1a1d20; --line:#343a40; --text:#f3f0e8; --muted:#aeb5ba; --accent:#ff3bd4; --crop:#ffd84a; --ok:#58d68d; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,sans-serif; }
    button,input { font:inherit; }
    button { border:1px solid var(--line); border-radius:8px; padding:9px 13px; background:#252a2f; color:var(--text); cursor:pointer; }
    button:hover { border-color:#6b747d; background:#2d3339; }
    button:disabled { opacity:.4; cursor:not-allowed; }
    button.primary { background:var(--accent); border-color:var(--accent); color:#180312; font-weight:750; }
    .app { display:grid; grid-template-columns:280px minmax(0,1fr); min-height:100vh; }
    aside { border-right:1px solid var(--line); background:#15181a; padding:18px 14px; overflow:auto; max-height:100vh; position:sticky; top:0; }
    h1 { font-size:19px; margin:0 0 5px; letter-spacing:-.02em; }
    .intro,.hint,.meta { color:var(--muted); font-size:13px; line-height:1.45; }
    .guide-list { display:grid; gap:5px; margin-top:18px; }
    .guide-item { width:100%; display:grid; grid-template-columns:1fr auto; gap:8px; text-align:left; padding:9px 10px; }
    .guide-item.active { border-color:var(--accent); background:#30202d; }
    .guide-item span:first-child { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .badge { min-width:24px; text-align:center; border-radius:999px; background:#3b4147; padding:1px 7px; font-size:12px; }
    .badge.has { background:var(--accent); color:#180312; font-weight:800; }
    main { min-width:0; display:flex; flex-direction:column; }
    .toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:9px; padding:12px 16px; border-bottom:1px solid var(--line); background:rgba(17,19,21,.96); position:sticky; top:0; z-index:20; }
    .position { min-width:150px; font-weight:700; }
    .spacer { flex:1; }
    label { color:var(--muted); font-size:13px; }
    input { width:92px; margin-left:6px; padding:8px; border-radius:7px; border:1px solid var(--line); background:#0e1012; color:var(--text); }
    .stage-wrap { flex:1; display:grid; place-items:center; padding:20px; overflow:auto; }
    .stage { position:relative; max-width:100%; line-height:0; box-shadow:0 16px 50px #0008; user-select:none; }
    .stage img { display:block; max-width:100%; max-height:calc(100vh - 122px); width:auto; height:auto; cursor:crosshair; }
    .overlay { position:absolute; inset:0; pointer-events:none; }
    .crop-marker { position:absolute; border:2px solid var(--crop); background:#ffd84a16; transform:translate(0,0); pointer-events:auto; cursor:context-menu; box-shadow:0 0 0 1px #0009; }
    .crop-marker::before,.crop-marker::after { content:""; position:absolute; background:var(--accent); box-shadow:0 0 0 1px #000; }
    .crop-marker::before { width:13px; height:3px; left:var(--point-x); top:var(--point-y); transform:translate(-50%,-50%); }
    .crop-marker::after { width:3px; height:13px; left:var(--point-x); top:var(--point-y); transform:translate(-50%,-50%); }
    .crop-label { position:absolute; top:4px; left:5px; padding:3px 5px; border-radius:4px; background:#121416dd; color:var(--crop); font:700 11px/1.1 ui-monospace,monospace; }
    .empty { padding:50px; color:var(--muted); text-align:center; }
    .status { min-height:20px; padding:0 20px 12px; color:var(--muted); font-size:13px; }
    .status.ok { color:var(--ok); }
    .status.error { color:#ff7777; }
    @media(max-width:800px) { .app{grid-template-columns:1fr} aside{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line)} .guide-list{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))} .toolbar{top:0} }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <h1>Crop marker</h1>
    <div class="intro">Vänsterklicka i bilden för att lägga till. Högerklicka på en gul ruta för att ta bort.</div>
    <div class="guide-list" id="guideList"></div>
  </aside>
  <main>
    <div class="toolbar">
      <button id="previous">← Föregående</button>
      <button id="next">Nästa →</button>
      <span class="position" id="position"></span>
      <span class="spacer"></span>
      <label>Cropstorlek <input id="cropSize" type="number" min="1" step="1"></label>
      <button id="clear">Rensa bilden</button>
      <button class="primary" id="save">Spara crop-plan</button>
    </div>
    <div class="stage-wrap" id="stageWrap"><div class="empty">Läser in guider…</div></div>
    <div class="status" id="status"></div>
  </main>
</div>
<script>
let state = null;
let current = 0;
let dirty = false;
const $ = (id) => document.getElementById(id);

function setStatus(message, kind='') { const node=$('status'); node.textContent=message; node.className='status '+kind; }
function markersFor(guide) { return state.markers[guide.key] || (state.markers[guide.key]=[]); }
function markDirty() { dirty=true; setStatus('Osparade ändringar'); }

function cropRect(guide, point) {
  const size=Math.min(Number($('cropSize').value),guide.source_width,guide.source_height);
  const sx=Math.round(point[0]/guide.display_width*guide.source_width);
  const sy=Math.round(point[1]/guide.display_height*guide.source_height);
  const left=Math.min(Math.max(sx-Math.floor(size/2),0),Math.max(guide.source_width-size,0));
  const top=Math.min(Math.max(sy-Math.floor(size/2),0),Math.max(guide.source_height-size,0));
  const totalWidth=guide.display_width+guide.image_offset[0];
  const totalHeight=guide.display_height+guide.image_offset[1];
  return {left:(left/guide.source_width*guide.display_width+guide.image_offset[0])/totalWidth*100,top:(top/guide.source_height*guide.display_height+guide.image_offset[1])/totalHeight*100,width:(size/guide.source_width*guide.display_width)/totalWidth*100,height:(size/guide.source_height*guide.display_height)/totalHeight*100,px:(point[0]/guide.display_width*guide.source_width-left)/size*100,py:(point[1]/guide.display_height*guide.source_height-top)/size*100};
}

function renderList() {
  const list=$('guideList'); list.replaceChildren();
  state.guides.forEach((guide,index)=>{
    const button=document.createElement('button'); button.className='guide-item'+(index===current?' active':'');
    const name=document.createElement('span'); name.textContent=guide.set_id;
    const badge=document.createElement('span'); const count=markersFor(guide).length; badge.className='badge'+(count?' has':''); badge.textContent=count;
    button.title=guide.scan_set+' / '+guide.set_id; button.append(name,badge); button.onclick=()=>{current=index;render();}; list.append(button);
  });
}

function renderStage() {
  const wrap=$('stageWrap'); wrap.replaceChildren();
  if(!state.guides.length){ const e=document.createElement('div');e.className='empty';e.textContent='Inga crop-guider hittades.';wrap.append(e);return; }
  const guide=state.guides[current];
  const stage=document.createElement('div'); stage.className='stage';
  const img=document.createElement('img'); img.src=guide.image_url; img.alt=guide.scan_set+' '+guide.set_id;
  const overlay=document.createElement('div'); overlay.className='overlay';
  markersFor(guide).forEach((point,index)=>{
    const rect=cropRect(guide,point); const marker=document.createElement('div'); marker.className='crop-marker';
    Object.assign(marker.style,{left:rect.left+'%',top:rect.top+'%',width:rect.width+'%',height:rect.height+'%','--point-x':rect.px+'%','--point-y':rect.py+'%'});
    const label=document.createElement('span');label.className='crop-label';label.textContent=String(index+1).padStart(2,'0');marker.append(label);
    marker.title='Högerklicka för att ta bort';
    marker.oncontextmenu=(event)=>{event.preventDefault();event.stopPropagation();markersFor(guide).splice(index,1);markDirty();render();};
    overlay.append(marker);
  });
  img.onclick=(event)=>{
    const rect=img.getBoundingClientRect();
    const rawX=(event.clientX-rect.left)/rect.width*(guide.display_width+guide.image_offset[0]);
    const rawY=(event.clientY-rect.top)/rect.height*(guide.display_height+guide.image_offset[1]);
    const x=Math.round(rawX-guide.image_offset[0]); const y=Math.round(rawY-guide.image_offset[1]);
    if(x<0||x>guide.display_width||y<0||y>guide.display_height){setStatus('Klicka i själva bilden, inte i rubrikfältet.','error');return;}
    markersFor(guide).push([x,y]);markDirty();render();
  };
  img.oncontextmenu=(event)=>event.preventDefault();
  stage.append(img,overlay);wrap.append(stage);
}

function render() {
  const guide=state.guides[current];
  $('position').textContent=guide?`${current+1} / ${state.guides.length} · ${guide.set_id}`:'0 / 0';
  $('previous').disabled=current===0; $('next').disabled=current>=state.guides.length-1;
  renderList(); renderStage();
}

async function save() {
  const cropSize=Number($('cropSize').value);
  if(!Number.isInteger(cropSize)||cropSize<=0){setStatus('Cropstorleken måste vara ett positivt heltal.','error');return;}
  $('save').disabled=true; setStatus('Sparar…');
  try {
    const response=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({crop_size:cropSize,markers:state.markers})});
    const result=await response.json(); if(!response.ok) throw new Error(result.error||'Kunde inte spara');
    dirty=false; setStatus(`Sparat ${result.crop_count} crop(s) till ${result.output}`,'ok');
  } catch(error) { setStatus(error.message,'error'); } finally { $('save').disabled=false; }
}

async function init() {
  try { const response=await fetch('/api/state'); state=await response.json(); $('cropSize').value=state.crop_size; render(); }
  catch(error){$('stageWrap').innerHTML='<div class="empty">Kunde inte läsa guiderna.</div>';setStatus(error.message,'error');}
}

$('previous').onclick=()=>{if(current>0){current--;render();}};
$('next').onclick=()=>{if(current<state.guides.length-1){current++;render();}};
$('clear').onclick=()=>{if(state&&state.guides[current]){state.markers[state.guides[current].key]=[];markDirty();render();}};
$('save').onclick=save;
$('cropSize').onchange=()=>{markDirty();renderStage();};
window.onkeydown=(event)=>{if(event.target.tagName==='INPUT')return;if(event.key==='ArrowLeft')$('previous').click();if(event.key==='ArrowRight')$('next').click();};
window.onbeforeunload=(event)=>{if(dirty){event.preventDefault();event.returnValue='';}};
init();
</script>
</body>
</html>'''


def make_handler(guides: list[Guide], output: Path):
    guide_by_index = {str(index): guide for index, guide in enumerate(guides)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {format % args}")

        def send_bytes(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/state":
                crop_size, markers = load_existing_markers(output, guides)
                self.send_json({"guides": [guide.public_dict(index) for index, guide in enumerate(guides)], "crop_size": crop_size, "markers": markers})
                return
            if path.startswith("/guide/"):
                guide = guide_by_index.get(path.removeprefix("/guide/"))
                if guide:
                    self.send_bytes(guide.image_path.read_bytes(), mimetypes.guess_type(guide.image_path.name)[0] or "application/octet-stream")
                    return
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/save":
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 2_000_000:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(length))
                crop_size = int(request["crop_size"])
                raw_markers = request.get("markers", {})
                if not isinstance(raw_markers, dict):
                    raise ValueError("markers must be an object")
                known = {guide.key for guide in guides}
                if any(key not in known for key in raw_markers):
                    raise ValueError("Unknown guide in marker data")
                markers = {key: [[int(point[0]), int(point[1])] for point in points] for key, points in raw_markers.items()}
                plan = build_crop_plan(guides, markers, crop_size)
                save_crop_plan(output, plan)
                count = sum(len(item["crops"]) for item in plan["cases"].values())
                self.send_json({"ok": True, "crop_count": count, "output": str(output.relative_to(ROOT)).replace("\\", "/")})
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a local browser UI for selecting manual review crops.")
    parser.add_argument("--guides-root", type=Path, default=DEFAULT_GUIDES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the page in the default browser.")
    args = parser.parse_args()
    guides = load_guides(args.guides_root)
    if not guides:
        raise SystemExit(f"No crop guides found under {args.guides_root}")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(guides, args.output))
    url = f"http://{args.host}:{server.server_port}/"
    print(f"Crop marker ready at {url}")
    print(f"Loaded {len(guides)} guide(s); saving to {args.output}")
    if args.open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
