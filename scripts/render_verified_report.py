"""Render the review report only from a complete, verified release manifest."""
from __future__ import annotations

import argparse
from collections import defaultdict
import html
import json
import os
from pathlib import Path
import statistics
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from incremental_cache import sha256_file,atomic_write_json
from generate_break_even_report_site import viewer_records,crop_viewer_workspace,read_annotations,DEFAULT_ANNOTATIONS

COHORTS={"primary_compressed_independent":"Independent compressed RAW61 film frames",
         "secondary_sequence_or_uncompressed":"Uncompressed / sequence RAW61 (secondary)",
         "diagnostic_flat_field":"Flat-field diagnostic (no film)",
         "secondary_same_sequence_target":"f/4.5 target; same-sequence RAW anchor",
         "historical_f8_target":"Historical f/8 target"}
COHORT_ORDER={key:index for index,key in enumerate(("primary_compressed_independent","secondary_sequence_or_uncompressed",
                                                   "secondary_same_sequence_target","historical_f8_target","diagnostic_flat_field"))}


def esc(value):return html.escape(str(value),quote=True)
def num(value,digits=3):return "—" if value is None else f"{value:.{digits}f}"
def fraction(a,b):return f"{a}/{b}" if b else "0/0 (none)"
def table(headings,rows,caption):
    return '<div class="table-wrap"><table><caption>'+esc(caption)+'</caption><thead><tr>'+''.join('<th scope="col">'+h+'</th>' for h in headings)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def worst(row,metric,mode="identity",role="candidate",scope="native_crop"):
    values=[m[role][metric] for m in row["measurements"] if m["scope_kind"]==scope and m[role]["transform"]==mode]
    return max(values) if values and all(v is not None for v in values) else None
def median(values):
    values=[v for v in values if v is not None]
    return statistics.median(values) if values else None

def median_with_count(values):
    values=list(values)
    return num(median(values))+" ("+fraction(sum(v is not None for v in values),len(values))+")"


def render(release,site):
    if release.get("schema")!=3:raise ValueError("Only a schema-3 verified release can produce the current report")
    attachments={}
    for key,record in release["evidence"].items():
        path=site/record["file"]
        if sha256_file(path)!=record["sha256"]:raise ValueError(f"Changed evidence: {key}")
        attachments[key]=json.loads(path.read_text(encoding="utf-8"))
    primary=[r for r in release["candidates"] if r["cohort"]=="primary_compressed_independent"]
    decisions=[r for r in primary if r["decision_level"]]
    budget=[r for r in decisions if r["within_primary_raw61_budget"]]
    aligned=[r for r in budget if r["alignment_review_pass"]]
    frames=release["summary"]["primary_frames"]
    first_fits=[]
    for key in {(r["slug"],r["set_id"]) for r in decisions}:
        matching=[r for r in budget if (r["slug"],r["set_id"])==key]
        if matching:first_fits.append(min(matching,key=lambda r:r["level"]))
    first_aligned=[r for r in first_fits if r["alignment_review_pass"]]
    bylevel=defaultdict(list)
    for row in primary:bylevel[row["level"]].append(row)
    dng=attachments["dng"];public=attachments["public"];combiner=attachments["combiner"];controlled=attachments["controlled"]
    lossy=next(r for r in dng["routes"] if r["level"]=="d001")
    ds=lossy["summary"]
    sections=[]
    sections.append(f'''<section id="question"><h2>Can a Pixel-Shift JPEG XL retain more useful archival information at a conventional RAW61 file size?</h2>
<p>The comparison retains that research question. The rendered-RGB route measures fidelity to a retained PS16 render at each frame’s actual compressed RAW61 byte budget. The DNG route tests a separate 200 MiB target while preserving the DNG workflow. Their evidence and denominators remain separate.</p>
<p>RAW61 denotes the conventional 61-megapixel single-shot raw route. PS16 denotes the higher-resolution image merged from a 16-frame pixel-shift sequence. The private inputs are camera scans of film; the flat-field and resolution-target controls are identified separately.</p>
<div class="questions"><article class="card"><h3>Rendered PS16 → JPEG XL</h3><p class="metric">{len(first_fits)}/{frames}</p><p>Primary frames have a tested candidate within their paired RAW61 byte budget. At each frame’s first fitting decision distance, {len(first_aligned)}/{len(first_fits)} have accepted registration.</p><p>Among those {len(first_aligned)} registered frames: {sum(r['native_color_closer_than_raw61'] for r in first_aligned)}/{len(first_aligned)} meet the native color comparison and {sum(r['native_structure_closer_than_raw61'] for r in first_aligned)}/{len(first_aligned)} meet the native structure comparison. These are separate screens, not an archival-quality score.</p><p>The complete eight-distance decision grid has {len(budget)}/{len(decisions)} budget-fitting frame–distance rows. Repeated distances are not additional captures.</p><a href="#rendered">Inspect rendered results</a></article>
<article class="card"><h3>PS16 DNG → JPEG XL inside DNG</h3><p class="metric">{ds['within_200_mib']}/{ds['files']}</p><p>Historical DNG files at d=0.01 fit 200 MiB. {ds['technical_passed']}/{ds['files']} pass the technical preservation audit.</p><p>Image-quality superiority over RAW61 remains <strong>unresolved</strong>. Camera-sample errors are published in camera codes; they are not display-color differences or recovered latitude.</p><a href="#dng">Inspect DNG results</a></article></div>
<p class="scope-note">A closer match to the PS16 reference is evidence of relative fidelity in this rendering chain. PS16 is not scene truth. Capture differences, demosaic, grain/noise, registration and interpolation contribute to the RAW61 baseline. No universal archival recommendation follows from these screens alone.</p></section>''')
    cohort_rows=[[esc(COHORTS.get(k,k)),v,"Included" if k=="primary_compressed_independent" else "Separate diagnostic / secondary evidence"] for k,v in sorted(release["summary"]["cohort_frames"].items(),key=lambda item:COHORT_ORDER[item[0]])]
    sections.append('<section id="scope"><h2>Captures and denominators</h2>'+table(["Cohort","Frames","Primary size comparison"],cohort_rows,"Current rendered-RGB corpus")+
        f'<p>The rendered corpus has {release["summary"]["frames"]} frames, {release["summary"]["native_crops"]} approved native crops and {release["summary"]["candidates"]} frame–distance rows. Ten distances are retained; d=1.0 and d=2.0 are visual stress controls. The primary cohort contributes {len(decisions)} decision rows and {len(primary)-len(decisions)} stress rows. The two Gold frames with uncompressed or sequence RAWs are excluded from the primary budget comparison. The f/4.5 target has no separate single-shot capture. The flat field contains no film.</p><p>The DNG corpus has 16 historical sources, including the older f/8 target in place of f/4.5. Its 12 primary film frames, two secondary Gold frames, one flat field and one historical target are shown explicitly below.</p></section>')
    rows=[];metric_rows=[]
    for level,items in sorted(bylevel.items()):
        within=[r for r in items if r["within_primary_raw61_budget"]]
        eligible=[r for r in within if r["alignment_review_pass"]]
        rows.append([level+ (" · stress" if not items[0]["decision_level"] else ""),len(items),
                     num(median(r["encoded_bytes"]/2**20 for r in items),2),num(median(r["size_vs_raw61_pct"] for r in items),1)+"%",
                     fraction(len(within),len(items)),fraction(len(eligible),len(within)),
                     fraction(sum(r["native_color_closer_than_raw61"] for r in eligible),len(eligible)),
                     fraction(sum(r["native_structure_closer_than_raw61"] for r in eligible),len(eligible))])
        metric_rows.append([level,median_with_count(worst(r,"delta_e00_p95") for r in items),
                            median_with_count(worst(r,"delta_e00_p95",role="raw61") for r in items),
                            median_with_count(worst(r,"delta_e00_p95",mode="negative_density_hard_print") for r in items),
                            median_with_count(worst(r,"structure_loss") for r in items),
                            median_with_count(worst(r,"structure_loss",role="raw61") for r in items),
                            median_with_count(worst(r,"structure_loss",scope="reduced_full_frame") for r in items)])
    stress=[r for r in bylevel["d200"] if r["within_primary_raw61_budget"] and r["alignment_review_pass"]]
    stress_note=f'<p class="scope-note">At the d=2.0 strong-loss control, {sum(r["native_color_closer_than_raw61"] for r in stress)}/{len(stress)} eligible frames meet the color screen and {sum(r["native_structure_closer_than_raw61"] for r in stress)}/{len(stress)} meet the structure screen. Machine-assisted inspection still found coarser texture and softened fine detail in selected control crops. Passing these relative screens therefore cannot define acceptable archival quality. The RAW61 baseline includes substantial capture and rendering differences, and high-pass mismatch includes grain and noise.</p>'
    sections.append('<section id="rendered"><h2>Rendered-RGB route: strict RAW61 budget</h2><p>A row fits only when <code>final JXL bytes ≤ paired RAW61 bytes</code>. There is no 5% allowance. Sizes include the released photographic metadata. Registration must be accepted with at least 80% valid crop support before a favorable comparison can be counted.</p>'+table(
        ["Distance","Frames","Median MiB","Median % of RAW61","Fit budget / frames","Aligned / fit","Native color / aligned fit","Native structure / aligned fit"],rows,"Separate screens at each distance; repeated frames, not independent samples")+
        '<p><strong>Native color:</strong> candidate patch ΔE00 p95 is no larger than the paired RAW61 error in both normal and hard-inversion modes, in every approved crop. <strong>Native structure:</strong> normal-mode high-pass mismatch is no larger than RAW61 in every approved crop. These relative screens do not imply that an error is invisible. “Aligned / fit” discloses any excluded comparisons.</p>'+stress_note+table(
        ["Distance","Native normal ΔE00","RAW61 normal ΔE00","Native hard-inversion ΔE00","Native HP loss","RAW61 native HP loss","10× box HP loss"],metric_rows,
        "Median of each frame’s worst native crop; parentheses give measurable frames / all frames. The 10× box column is a separate full-frame diagnostic")+
        '<p>ΔE00 is computed from 64×64 patch means in linear light, converted through XYZ D50 to Lab D50. HP loss is mismatch RMS divided by reference high-pass RMS, using a 5×5 box filter. A 10× linear-light box reduction removes much native grain and fine detail before measurement. Its small errors must not be read as proof of grain preservation. Every crop, mode and scope remains available in the CSV.</p></section>')
    collection_rows=[[r["level"],r["primary_frames"],num(r["jxl_total_bytes"]/2**30,3),num(r["raw61_total_bytes"]/2**30,3),
                      num(100*r["jxl_total_bytes"]/r["raw61_total_bytes"],1)+"%"] for r in release["collection_sizes"]]
    sections.append('<details><summary>Collection storage across the 12 primary frames</summary>'+table(
        ["Distance","Frames","JXL total GiB","RAW61 total GiB","Total bytes / RAW61 total"],collection_rows,
        "Actual measured collection cost; a collection total does not imply that every frame fits its own budget")+'</details>')
    frame_rows=[]
    for frame in sorted(release["frames"],key=lambda f:(COHORT_ORDER[f["cohort"]],f["scan_set"],f["set_id"])):
        candidates=[r for r in release["candidates"] if r["slug"]==frame["slug"] and r["set_id"]==frame["set_id"] and r["decision_level"]]
        matches=[r for r in candidates if r["within_primary_raw61_budget"]]
        first=min(matches,key=lambda r:r["level"]) if matches else None
        ordered=sorted(candidates,key=lambda r:r["level"])
        if frame["cohort"]!="primary_compressed_independent":crossing="Not in primary budget cohort"
        elif first is None:crossing="No crossing established through d030"
        elif first==ordered[0]:crossing="At or below lowest tested distance d003"
        else:crossing=ordered[ordered.index(first)-1]["level"]+" (over) → "+first["level"]+" (fits)"
        frame_rows.append([esc(frame["scan_set"])+" / "+esc(frame["set_id"]),esc(COHORTS.get(frame["cohort"],frame["cohort"])),
                           num(frame["raw61"]["bytes"]/2**20,2),crossing,
                           "—" if first is None else num(first["encoded_bytes"]/2**20,2),
                           *["—" if first is None else "Registration not accepted" if not first["alignment_review_pass"] else "Meets comparison" if first[metric] else "Does not meet comparison"
                             for metric in ("native_color_closer_than_raw61","native_structure_closer_than_raw61")]])
    sections.append('<details><summary>Frame-by-frame budget and secondary cohorts</summary><p>Intervals bracket the first tested size crossing. The exact crossing between tested distances was not measured; no interpolated optimum is claimed. Distance labels use hundredths: d025 is 0.25 and d200 is 2.0. The DNG route’s 200 MiB allowance is a separate byte budget.</p>'+table(["Frame","Cohort","RAW MiB","Tested crossing interval","First fitting JXL MiB","Native color at first fit","Native structure at first fit"],frame_rows,"Eight decision distances only; no size verdict for secondary or diagnostic captures")+'</details>')
    sizes=[{"scan_set":r["scan_set"],"set_id":r["set_id"],"level":r["level"],"raw61_size_mib":str(r["raw61_bytes"]/2**20),"retained_size_mib":str(r["encoded_bytes"]/2**20)} for r in release["candidates"]]
    paths=[site/path for path in release["asset_hashes"] if path.endswith("metadata.json")]
    viewers,_=viewer_records([p.with_name("index.html") for p in paths],site/"index.html",read_annotations(DEFAULT_ANNOTATIONS),sizes)
    if len(viewers)!=release["summary"]["native_crops"]:raise ValueError("Viewer/crop denominator mismatch")
    sections.append('<section id="visual"><h2>Inspect the same measured crops</h2><p>Choose <strong>PS16 reference</strong> on the left to isolate codec changes, or <strong>RAW61 baseline</strong> for the research comparison. All five modes share a reference-derived recipe. Exposure acts in linear light before the selected transformation. Display conversion is ICC-managed to sRGB; the canvas is 8-bit, while its input buffers retain RGB16.</p>'+crop_viewer_workspace(viewers)+'<p>Hard inversion is a mathematical edit-sensitivity proxy, not a calibrated film inversion. Black/white and point-curve controls are exploratory display edits and are not included in the published metric screens. Only the two adjacent quality levels may be prefetched for the current crop.</p></section>')
    if "contexts" in attachments:
        contexts=attachments["contexts"]
        sections.append('<details><summary>PS16 context maps and approved crop locations</summary><p>These small, neutral PS16 maps locate the approved crops. They are navigation aids; use the RGB16 viewer for comparisons.</p><div class="context-grid">'+''.join('<figure class="context-card"><a href="'+esc(c['file'])+'"><img loading="lazy" src="'+esc(c['file'])+'" alt="'+esc(c['set_id'])+' crop locations"></a><figcaption>'+esc(c['scan_set']+' / '+c['set_id'])+'</figcaption></figure>' for c in contexts['records'])+'</div></details>')
    dng_rows=[];dng_cohorts=[]
    for route in dng["routes"]:
        rs=route["summary"];records=route["records"]
        dng_rows.append(["d=0.01" if route["level"]=="d001" else "Lossless",rs["files"],fraction(rs["technical_passed"],rs["files"]),fraction(rs["within_200_mib"],rs["files"]),
                         num(min(r["candidate_bytes"] for r in records)/2**20,2)+"–"+num(max(r["candidate_bytes"] for r in records)/2**20,2),fraction(rs["exact_in_all_checked_crops"],rs["files"])])
        for cohort in sorted(rs["cohort_frames"],key=COHORT_ORDER.get):
            selected=[r for r in records if r["cohort"]==cohort]
            dng_cohorts.append([route["level"],esc(COHORTS[cohort]),len(selected),fraction(sum(r["within_200_mib"] for r in selected),len(selected)),fraction(sum(r["technical_pass"] for r in selected),len(selected))])
    sections.append('<section id="dng"><h2>DNG route: 200 MiB budget and preservation</h2>'+table(["Route","Files","Technical pass","≤200 MiB","Size range MiB","Exact in all checked crops"],dng_rows,"The historical DNG corpus is assessed independently of the rendered-RGB cohort")+
        '<p>All candidates were rehashed. Existing full-tile decode and Adobe DNG Converter acceptance records were reused only when the file hash matched. Preservation metadata and selected camera-sample tiles were checked afresh, using the pinned libjxl decoder. Lossless exactness here refers to the checked crops; full-file pixel identity was not re-established by decoding every tile in this repair.</p>'+table(["Route","Cohort","Files","Budget / cohort","Technical / cohort"],dng_cohorts,"Explicit DNG denominators")+
        '<p><strong>Quality question still open:</strong> the previous camera-RGB CIEDE2000 values, ratios against rendered RAW61 errors and “15/16 archive-value” verdict are withdrawn. A common validated end-to-end rendering and inversion comparison is required to establish a RAW61 image-quality advantage. Small camera-code errors and application acceptance do not answer that question.</p></section>')
    pubrows=[]
    for case in public["records"]:
        for level in case["levels"]:
            m={r["transform"]:r for r in level["measurements"]}
            pubrows.append([esc(case["name"]),case["conversion"]["source_precision_bits"],level["distance"],num(level["encoded_bytes"]/2**20,3),
                            num(m["identity"]["delta_e00_p95"]),num(m["negative_density_hard_print"]["delta_e00_p95"]),num(m["identity"]["structure_loss"])])
    sections.append('<section id="public"><h2>Public reproducibility check</h2><p>Six public 2048-pixel center crops are encoded at lossless, 0.03, 0.05 and 0.10. Original 8-bit sources remain explicitly 8-bit sources; grayscale ICC conversion is independently checked. Lossless requires exact decoded pixels and profile. These files test the codec and edit-sensitivity method, and contribute no RAW61-versus-PS16 evidence.</p>'+table(["Public image","Source bits","Distance","MiB","Normal ΔE00 p95","Hard inversion ΔE00 p95","Native HP loss"],pubrows,"All six files × four distances; original precision is declared")+
        '<details><summary>Public d=0.05 comparison panels</summary><p>These resampled panels illustrate appearance. The numerical measurements use the full 2048-pixel crops; small previews cannot establish native-detail preservation.</p><div class="public-figure-grid">'+''.join('<figure class="public-figure"><a href="'+esc(c['figure'])+'"><img loading="lazy" src="'+esc(c['figure'])+'" alt="'+esc(c['name'])+' reference and candidate"></a><figcaption>'+esc(c['name'])+'</figcaption></figure>' for c in public['records'])+'</div></details></section>')
    combrows=[]
    for case in combiner["cases"]:
        for c in case["crops"]:
            m=c["metrics"]
            combrows.append([esc(case["label"])+" / "+esc(c["name"]),*[m["range_errors"][b]["closer_to_anchor"] for b in ("shadow","midtone","highlight")],
                             num(m["detail_correlation"]["pixelshift2dng"]),num(m["detail_correlation"]["sony_arq"])])
    sections.append('<section id="combiner"><h2>Combiner audit: tonal agreement, not recovered latitude</h2><p>'+esc(combiner["scope"])+'. '+esc(combiner["interpretation"])+'.</p><p>'+esc(combiner["method"])+'.</p>'+table(["Crop","Closer shadows","Closer midtones","Closer highlights","PS2DNG detail r","Sony detail r"],combrows,"Agreement with the first source ARW after scalar exposure matching; two sequences only")+
        '<details><summary>Corrected combiner panels</summary><div class="public-figure-grid">'+''.join('<figure class="public-figure"><a href="'+esc(c['figure'])+'"><img loading="lazy" src="'+esc(c['figure'])+'" alt="'+esc(case['label']+' / '+c['name'])+'"></a><figcaption>'+esc(case['label']+' / '+c['name'])+'</figcaption></figure>' for case in combiner['cases'] for c in case['crops'])+'</div></details></section>')
    sections.append('<section id="capture"><h2>Capture latitude is a separate experiment</h2><p>'+esc(controlled["scope"])+ '</p><p>'+esc(controlled["review_note"])+ '</p><p>This sensor-domain experiment concerns exposure choice and recoverable raw signal. It does not rank the two combiners or quantify loss from a rendered JPEG XL. Its leave-one-out reference excludes the scored frame, but its normalization and signal-band selection still use the bracket; the bracket is not an independent scene-truth measurement.</p><p><a href="data/controlled-evidence.json">Download the complete controlled-exposure evidence</a>.</p></section>')
    lineage=attachments["lineage"]
    quantization=[c for f in lineage["frames"] for c in f["raw_viewer_quantization"]]
    boundary=[r for c in quantization for r in c["native_highpass_boundary_sensitivity"]]
    defined=[r for r in boundary if r["relative_screen_changed"] is not None]
    display_error=max(v for c in quantization for v in c["max_display_code_error_by_mode"].values())
    sections.append('<details><summary>Viewer quantization and crop-boundary checks</summary><p>The aligned RAW viewer buffer differs from the floating-point measurement input by at most '+num(display_error,0)+' sRGB display codes across the checked crops and five modes at zero exposure adjustment. Candidate and PS16 buffers retain their exact decoded RGB16 codes. Full per-crop errors and any resampling values outside 0–1 are disclosed in the lineage file.</p><p>Removing the two padding-dependent output pixels on every side of the native 5×5 high-pass filter changes '+str(sum(r["relative_screen_changed"] for r in defined))+'/'+str(len(defined))+' defined crop–distance comparisons with RAW61; '+str(len(boundary)-len(defined))+' comparisons have insufficient reference energy. These repeated crop/level checks are not additional captured frames. All native source-resampling footprints were checked to remain inside the RAW image.</p></details>')
    sections.append('<section id="lineage"><h2>What the retained files can establish</h2><p>Legacy encodes did not record their input content hashes at encode time. This rebuild adopts those files using the retained job mapping, present source hashes, dimensions, precision, ICC checks, complete decoding and measured agreement with pixel-verified render sources. It does not claim that historical encoder-input identity has been proved cryptographically or that the files have been reproduced bit for bit by re-encoding.</p><p>The neutral RawTherapee preset uses camera white balance and camera input profiles. The same preset can resolve differently for RAW and DNG inputs; the retained renders do not expose every resolved internal parameter. This is a comparison of the retained rendering workflow, not a controlled isolation of sampling alone. The lineage download records available capture and white-balance metadata, codestream preservation during metadata repair, and quantization of the aligned RAW viewer buffer.</p></section>')
    methods=''.join('<dt>'+esc(k.replace('_',' ').capitalize())+'</dt><dd>'+esc(v)+'</dd>' for k,v in release["method"].items())
    links=''.join('<li><a download href="'+esc(r['file'])+'">'+esc(k.capitalize())+' evidence JSON</a></li>' for k,r in release['evidence'].items())
    links+='<li><a href="data/review-notes.md">Machine-assisted review record</a></li>'
    sections.append('<section id="method"><h2>Methods, provenance and downloads</h2><dl>'+methods+'</dl><p>Each frame has a real-image RGB16 lossless pilot with pixel, ICC and photographic-metadata checks. Retained render sources are explicitly identified as adopted renders, with hashes and pixel equality checked against the original TIFFs. Lossy decoder profiles are converted through their actual ICC matrices and transfer curves; they are never silently relabeled as the source profile.</p><ul><li><a download href="data/release.json">Complete release manifest and measurements JSON</a></li><li><a download href="data/measurements.csv">All measurements CSV</a></li>'+links+'<li><a href="data/reproduction.md">Reproduction instructions and review limits</a></li></ul><p>Private source scans, source paths and full encoded captures are not included. Approved crop derivatives, small context maps, public-source provenance, numerical results, content hashes and recipes are available. A public-only reproduction exercises the method; reproducing the private capture comparisons requires owner access to the private sources.</p></section>')
    css=(ROOT/"src/report_styles.css").read_text(encoding="utf-8")
    css+='\ncaption{text-align:left;font-weight:bold;padding:12px 0} .table-wrap{overflow-x:auto;margin-bottom:18px} th{vertical-align:bottom} td{vertical-align:top} dl{display:grid;grid-template-columns:minmax(110px,180px) 1fr;gap:10px}dt{font-weight:bold}dd{margin:0}details{margin:18px 0}summary{cursor:pointer;font-weight:bold}.public-figure img{width:100%;height:auto}nav{display:flex;flex-wrap:wrap;gap:14px;margin:20px 0}.scope-note{margin-top:16px;padding:14px;border-left:4px solid #466a81;background:#edf3f6}@media(max-width:600px){header,main{padding:16px}dl{display:block}dd{margin-bottom:12px}}'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAW61 and Pixel-Shift JPEG XL — verified local review</title><style>'+css+'</style></head><body><header><p class="muted">Validated local report · awaiting owner review</p><h1>RAW61 and Pixel-Shift JPEG XL</h1><p class="lead">What the retained scans show about JPEG XL fidelity at RAW61 and 200 MiB storage budgets.</p><p>Release <code>'+esc(release['run_id'])+'</code></p><nav aria-label="Report sections">'+''.join('<a href="#'+a+'">'+b+'</a>' for a,b in (("question","Research question"),("rendered","RAW61 budget"),("visual","Crop viewer"),("dng","DNG · 200 MiB"),("public","Public test"),("combiner","Combiners"),("capture","Capture latitude"),("method","Downloads")))+'</nav></header><main>'+''.join(sections)+'</main></body></html>\n'


def write_report(release,site):
    redirects={}
    for relative in release["asset_hashes"]:
        if not relative.endswith("/metadata.json"):continue
        path=(site/relative).with_name("index.html")
        metadata=json.loads((site/relative).read_text(encoding="utf-8"))
        query=urlencode({"scan":metadata["scan_set"],"frame":metadata["set_id"],"crop":metadata["crop_name"]})
        target=os.path.relpath(site/"index.html",path.parent).replace("\\","/")+"?"+query+"#visual"
        path.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Current crop viewer</title><meta http-equiv="refresh" content="0;url='+esc(target)+'"><p><a href="'+esc(target)+'">Open the verified report and crop viewer</a>.</p></html>\n',encoding="utf-8")
        redirects[path.relative_to(site).as_posix()]=sha256_file(path)
    (site/"index.html").write_text(render(release,site),encoding="utf-8")
    atomic_write_json(site/"data/site-build.json",{"release_sha256":sha256_file(site/"data/release.json"),
                                                  "html_sha256":sha256_file(site/"index.html"),"redirects":redirects})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site",type=Path,default=ROOT/"site")
    args=p.parse_args();release=json.loads((args.site/"data/release.json").read_text(encoding="utf-8"))
    write_report(release,args.site)
    print("Rendered",release["run_id"])
    return 0


if __name__=="__main__":raise SystemExit(main())
