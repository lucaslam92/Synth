#!/usr/bin/env python3
"""
feature_map.py — HTML Feature Map Renderer

Reads FUNCTION_INDEX.json (produced by /synth-index) and renders an interactive,
single-file HTML visualization of the codebase's feature map.

No graphify or tree-sitter required — only the Python standard library.

Usage:
  python feature_map.py /path/to/repo
  python feature_map.py /path/to/repo -o ./my-output
  python feature_map.py /path/to/repo --index /custom/FUNCTION_INDEX.json

Index discovery order (first found wins):
  1. --index flag (explicit path)
  2. {repo_root}/synth-out/FUNCTION_INDEX.json        (canonical)
  3. {repo_root}/feature-map-out/FUNCTION_INDEX.json  (legacy fallback)

Progress → stderr
JSON summary → stdout
"""

from __future__ import annotations
import sys
import json
import argparse
import textwrap
from pathlib import Path
from datetime import datetime, timezone


# ════════════════════════════════════════════════════════════════
# INDEX DISCOVERY
# ════════════════════════════════════════════════════════════════

def find_index(repo_root: Path, explicit: str | None) -> Path | None:
    """Return the path to FUNCTION_INDEX.json, or None if not found."""
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for candidate in [
        repo_root / "synth-out" / "FUNCTION_INDEX.json",
        repo_root / "feature-map-out" / "FUNCTION_INDEX.json",
    ]:
        if candidate.exists():
            return candidate
    return None


# ════════════════════════════════════════════════════════════════
# PAGE DATA BUILDER  (reads from FUNCTION_INDEX.json)
# ════════════════════════════════════════════════════════════════

def _build_page_data(index: dict) -> dict:
    """
    Convert FUNCTION_INDEX.json into the page-data dict expected by the HTML template.
    Mermaid diagram strings are read directly from features[name].diagrams — no
    networkx graph required.
    """
    features_idx = index.get("features", {})
    functions_idx = index.get("functions", {})
    repo_name = Path(index.get("source_repo", "repo")).name

    page_features = []
    for fname, fdata in features_idx.items():
        ep_ids   = fdata.get("entry_point_ids", [])
        ep_set   = set(ep_ids)
        member_ids = fdata.get("all_function_ids", [])

        members = []
        for mid in member_ids:
            func = functions_idx.get(mid)
            if not func:
                continue
            members.append({
                "id":         mid,
                "label":      func.get("label", mid),
                "file_path":  func.get("file_path", ""),
                "line_start": func.get("line_start"),
                "line_end":   func.get("line_end"),
                "signature":  func.get("signature", ""),
                "docstring":  func.get("docstring", ""),
                "kind":       func.get("kind", "unknown"),
                "entry_kind": func.get("entry_kind", ""),
            })

        members.sort(key=lambda m: (
            0 if m["id"] in ep_set else 1,
            m["file_path"],
            m.get("line_start") or 0,
        ))

        page_features.append({
            "id":               fdata.get("feature_id", f"feat_{fname}"),
            "name":             fname,
            "member_count":     fdata.get("function_count", len(members)),
            "primary_files":    fdata.get("primary_files", []),
            "entry_point_ids":  ep_ids,
            "members":          members,
            "diagrams":         fdata.get("diagrams", {}),  # pre-rendered Mermaid strings
        })

    stats = index.get("statistics", {})
    return dict(
        repo_name=repo_name,
        generated_at=index.get("generated_at", datetime.now(timezone.utc).isoformat()),
        features=page_features,
        total_functions=stats.get("total_functions", 0),
        total_features=stats.get("total_features", 0),
    )


# ════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ════════════════════════════════════════════════════════════════

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Feature Map</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f0f1a;--bg2:#1a1a2e;--bg3:#252540;--border:#2a2a4e;
  --text:#e0e0e0;--text2:#aaa;--text3:#555;
  --accent:#4E79A7;--teal:#76B7B2;--orange:#F28E2B;--green:#59A14F;
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",monospace;display:flex;height:100vh;overflow:hidden;font-size:13px}
#sidebar{width:280px;min-width:200px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
#search-wrap{padding:10px 12px;border-bottom:1px solid var(--border)}
#search{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:7px 10px;border-radius:6px;font-size:12px;outline:none}
#search:focus{border-color:var(--accent)}
#feat-list{flex:1;overflow-y:auto;padding:4px 0}
.fi{padding:8px 14px;cursor:pointer;border-left:3px solid transparent;transition:background .1s}
.fi:hover{background:var(--bg3)}
.fi.active{background:var(--bg3);border-left-color:var(--accent)}
.fi-name{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fi-sub{font-size:11px;color:var(--text3);margin-top:2px}
#sb-foot{padding:8px 14px;border-top:1px solid var(--border);font-size:11px;color:var(--text3)}
#main{flex:1;overflow-y:auto;display:flex;flex-direction:column}
#hdr{background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 22px;flex-shrink:0}
#hdr h1{font-size:15px;font-weight:600}
#hdr-sub{font-size:11px;color:var(--text3);margin-top:3px}
#content{padding:22px;flex:1}
.det{display:none}
.det.active{display:block}
.det-title{font-size:19px;font-weight:700;margin-bottom:6px}
.det-files{margin-bottom:18px}
.det-files span{display:inline-block;background:var(--bg3);padding:2px 8px;border-radius:4px;font-size:11px;margin:2px 4px 2px 0;color:var(--text2)}
.sec{margin-bottom:26px}
.sec-title{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px;padding-bottom:5px;border-bottom:1px solid var(--border)}
.ep-card{background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:12px 15px;margin-bottom:10px}
.ep-sig{font-family:monospace;font-size:12px;color:var(--teal);margin-bottom:5px;word-break:break-all}
.ep-loc{font-size:11px;color:var(--text3);margin-bottom:4px}
.ep-doc{font-size:11px;color:var(--text2);font-style:italic}
.chain-box{background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:14px;margin-bottom:12px;overflow-x:auto}
.chain-label{font-size:11px;color:var(--text3);margin-bottom:8px}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:7px 10px;font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;border-bottom:1px solid var(--border)}
td{padding:7px 10px;font-size:12px;border-bottom:1px solid rgba(42,42,78,.4);vertical-align:top}
tr:hover td{background:var(--bg3)}
.fn{font-family:monospace;color:var(--teal)}
.fn.ep{color:var(--orange);font-weight:600}
.loc{color:var(--text3);font-size:11px}
.kbadge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;text-transform:uppercase}
.kbadge.function{background:rgba(78,121,167,.2);color:var(--accent)}
.kbadge.class{background:rgba(242,142,43,.2);color:var(--orange)}
.kbadge.method{background:rgba(118,183,178,.2);color:var(--teal)}
.kbadge.dataclass{background:rgba(89,161,79,.2);color:var(--green)}
.kbadge.schema{background:rgba(89,161,79,.3);color:#7ecf75}
.kbadge.interface{background:rgba(118,183,178,.25);color:var(--teal)}
.kbadge.type{background:rgba(118,183,178,.15);color:#9dd4d0}
.kbadge.unknown{background:rgba(85,85,85,.2);color:var(--text3)}
.ekbadge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;text-transform:uppercase;margin-left:4px;vertical-align:middle}
.ekbadge.ROUTE{background:rgba(228,87,86,.25);color:#e45756}
.ekbadge.CLI_COMMAND,.ekbadge.CLI_ENTRY{background:rgba(242,142,43,.25);color:var(--orange)}
.ekbadge.EVENT_HANDLER{background:rgba(118,183,178,.25);color:var(--teal)}
.ekbadge.EXPORT{background:rgba(78,121,167,.25);color:var(--accent)}
.ekbadge.TASK{background:rgba(176,122,162,.25);color:#b07aa2}
.doc-cell{color:var(--text3);font-size:11px;font-style:italic;max-width:300px}
#welcome{text-align:center;padding:60px 20px;color:var(--text3)}
#welcome h2{font-size:17px;color:var(--text2);margin-bottom:8px}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg2)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<div id="sidebar">
  <div id="search-wrap"><input id="search" type="text" placeholder="🔍 Search features / functions / files..." autocomplete="off"></div>
  <div id="feat-list"></div>
  <div id="sb-foot"></div>
</div>
<div id="main">
  <div id="hdr"><h1>📦 Feature Map — <span id="rname"></span></h1><div id="hdr-sub"></div></div>
  <div id="content">
    <div id="welcome"><h2>Select a feature module from the sidebar</h2><p>Auto-detected from source · call chains · function tables</p></div>
    <div id="det-container"></div>
  </div>
</div>
<script>
mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'loose'});

const D = __DATA_PLACEHOLDER__;

document.getElementById('rname').textContent = D.repo_name;
document.getElementById('hdr-sub').textContent =
  `${D.total_features} feature modules · ${D.total_functions} functions · Generated ${new Date(D.generated_at).toLocaleString()}`;
document.getElementById('sb-foot').textContent = `${D.total_features} feature modules`;

const flist = document.getElementById('feat-list');
D.features.forEach((f,i)=>{
  const d = document.createElement('div');
  d.className='fi'; d.dataset.i=i;
  d.innerHTML=`<div class="fi-name" title="${esc(f.name)}">${esc(f.name)}</div><div class="fi-sub">${f.member_count} functions${f.primary_files[0]?' · '+esc(f.primary_files[0]):''}`;
  d.onclick=()=>show(i);
  flist.appendChild(d);
});

const dc = document.getElementById('det-container');
D.features.forEach((f,i)=>{
  const epSet = new Set(f.entry_point_ids);

  const epMembers = f.members.filter(m=>epSet.has(m.id));
  const epHTML = epMembers.length ? epMembers.map(m=>`
    <div class="ep-card">
      <div class="ep-sig">${esc(m.signature||m.label)}${m.entry_kind?`<span class="ekbadge ${esc(m.entry_kind)}">${esc(m.entry_kind)}</span>`:''}</div>
      <div class="ep-loc">📁 ${esc(m.file_path)}${m.line_start?` : L${m.line_start}–${m.line_end||'?'}`:''}</div>
      ${m.docstring?`<div class="ep-doc">${esc(m.docstring.substring(0,200))}</div>`:''}
    </div>`).join('')
  : '<p style="color:var(--text3);font-size:12px">(No entry points identified)</p>';

  const chainHTML = Object.entries(f.diagrams).map(([epId,mmd])=>{
    const ep = f.members.find(m=>m.id===epId);
    const uid = `mmd_${f.id}_${epId}`.replace(/[^a-zA-Z0-9]/g,'_');
    return `<div class="chain-box"><div class="chain-label">Call chain from: ${esc(ep?ep.label:epId)}</div>
      <div class="mermaid" id="${uid}">${esc(mmd)}</div></div>`;
  }).join('') || '<p style="color:var(--text3);font-size:12px">(No call chain data)</p>';

  const rows = f.members.map(m=>`<tr>
    <td><span class="fn ${epSet.has(m.id)?'ep':''}">${esc(m.label)}</span>${m.entry_kind?`<span class="ekbadge ${esc(m.entry_kind)}">${esc(m.entry_kind)}</span>`:''}</td>
    <td><span class="kbadge ${m.kind}">${m.kind}</span></td>
    <td><span class="loc">${esc(m.file_path)}${m.line_start?':'+m.line_start:''}</span></td>
    <td><span class="doc-cell">${esc((m.docstring||'').substring(0,80))}</span></td>
  </tr>`).join('');

  const div = document.createElement('div');
  div.className='det'; div.id=`det-${i}`;
  div.innerHTML=`
    <div class="det-title">${esc(f.name)}</div>
    <div class="det-files">${f.primary_files.map(fp=>`<span>${esc(fp)}</span>`).join('')}</div>
    <div class="sec"><div class="sec-title">🚪 Entry Points</div>${epHTML}</div>
    ${Object.keys(f.diagrams).length?`<div class="sec"><div class="sec-title">🔗 Call Chains</div>${chainHTML}</div>`:''}
    <div class="sec">
      <div class="sec-title">📋 All Functions (${f.member_count})</div>
      <table><thead><tr><th>Function / Class</th><th>Type</th><th>Location</th><th>Description</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div>`;
  dc.appendChild(div);
});

let cur = -1;
function show(i){
  document.getElementById('welcome').style.display='none';
  if(cur>=0){
    document.getElementById(`det-${cur}`)?.classList.remove('active');
    flist.children[cur]?.classList.remove('active');
  }
  cur=i;
  const det = document.getElementById(`det-${i}`);
  det?.classList.add('active');
  flist.children[i]?.classList.add('active');
  flist.children[i]?.scrollIntoView({block:'nearest'});
  document.getElementById('main').scrollTop=0;
  det?.querySelectorAll('.mermaid').forEach(async el=>{
    if(el.dataset.ok) return;
    el.dataset.ok='1';
    const code=el.textContent; el.textContent='';
    try{
      const {svg}=await mermaid.render(el.id||'m'+Math.random().toString(36).slice(2),code);
      el.innerHTML=svg;
    }catch{el.textContent='(Call chain render failed)';el.style.color='var(--text3)';}
  });
}

document.getElementById('search').addEventListener('input',e=>{
  const q=e.target.value.toLowerCase().trim();
  Array.from(flist.children).forEach((el,i)=>{
    const f=D.features[i];
    const hit=!q||f.name.toLowerCase().includes(q)
      ||f.primary_files.some(fp=>fp.toLowerCase().includes(q))
      ||f.members.some(m=>m.label.toLowerCase().includes(q)||m.file_path.toLowerCase().includes(q));
    el.style.display=hit?'':'none';
  });
});

function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

if(D.features.length) show(0);
</script>
</body></html>"""


# ════════════════════════════════════════════════════════════════
# GENERATE HTML
# ════════════════════════════════════════════════════════════════

def generate_html(index_path: Path, html_out: Path) -> dict:
    index     = json.loads(index_path.read_text(encoding="utf-8"))
    page_data = _build_page_data(index)
    html = _HTML.replace("__DATA_PLACEHOLDER__", json.dumps(page_data, ensure_ascii=False), 1)
    html_out.write_text(html, encoding="utf-8")
    kb = html_out.stat().st_size // 1024
    print(f"  ✅ functionality.html ({kb} KB) → {html_out}", file=sys.stderr)
    return index


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="feature_map",
        description="HTML Feature Map Renderer — reads FUNCTION_INDEX.json, writes HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Requires FUNCTION_INDEX.json produced by /synth-index.

        Examples:
          python feature_map.py .
          python feature_map.py /path/to/repo -o ./my-output
          python feature_map.py . --index /custom/FUNCTION_INDEX.json
        """),
    )
    parser.add_argument("root",    nargs="?", default=".", help="Repository root (default: .)")
    parser.add_argument("-o", "--output", default="feature-map-out",
                        help="Output directory for HTML (default: ./feature-map-out)")
    parser.add_argument("--index", default=None,
                        help="Explicit path to FUNCTION_INDEX.json (overrides auto-discovery)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"❌  '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    index_path = find_index(root, args.index)
    if index_path is None:
        print("❌  No FUNCTION_INDEX.json found.", file=sys.stderr)
        print(f"    Run first:  /synth-index {root}", file=sys.stderr)
        print(f"    Or pass:    --index /path/to/FUNCTION_INDEX.json", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🌐  Feature Map Renderer", file=sys.stderr)
    print(f"   Index  : {index_path}", file=sys.stderr)
    print(f"   Output : {out_dir.resolve()}\n", file=sys.stderr)

    html_path = out_dir / "functionality.html"
    index     = generate_html(index_path, html_path)

    print(f"\n✅  Done!  Open in any browser:", file=sys.stderr)
    print(f"   {html_path.resolve()}", file=sys.stderr)
    print(file=sys.stderr)

    stats = index.get("statistics", {})
    print(json.dumps({
        "status":    "ok",
        "html_path": str(html_path.resolve()),
        "features":  stats.get("total_features", 0),
        "functions": stats.get("total_functions", 0),
    }))


if __name__ == "__main__":
    main()
