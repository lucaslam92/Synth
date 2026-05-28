#!/usr/bin/env python3
"""
feature_map.py — Codebase Feature Map Generator

Converts any codebase into:
  1. functionality.html  — Interactive browser feature map (visual)
  2. FUNCTION_INDEX.json — Structured index for LLM code navigation

Uses Graphify's Python API for graph construction and community detection,
then supplements with a second AST pass to extract line ranges, signatures,
and docstrings that Graphify does not store.

Usage:
  python feature_map.py .                        # analyze current directory
  python feature_map.py /path/to/repo            # analyze specific directory
  python feature_map.py . -o ./out               # custom output directory
  python feature_map.py . --no-html              # JSON index only
  python feature_map.py . --no-json              # HTML only

Progress is written to stderr; a JSON summary line is written to stdout on success.

Required dependencies (auto-installed on first run):
  graphifyy, networkx, tree-sitter, tree-sitter-python,
  tree-sitter-javascript, tree-sitter-typescript
"""

from __future__ import annotations
import sys
import json
import re
import argparse
import textwrap
import subprocess
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone


# ════════════════════════════════════════════════════════════════
# 0. DEPENDENCY BOOTSTRAP  (runs before anything else)
# ════════════════════════════════════════════════════════════════

_REQUIRED = [
    "graphifyy",
    "networkx",
    "tree-sitter",
    "tree-sitter-python",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
]

_IMPORT_NAME = {
    "graphifyy":               "graphify",
    "tree-sitter":             "tree_sitter",
    "tree-sitter-python":      "tree_sitter_python",
    "tree-sitter-javascript":  "tree_sitter_javascript",
    "tree-sitter-typescript":  "tree_sitter_typescript",
}


def _ensure_deps() -> None:
    """Check all required packages; auto-install any that are missing."""
    import importlib
    missing = []
    for pkg in _REQUIRED:
        mod = _IMPORT_NAME.get(pkg, pkg.replace("-", "_"))
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return

    print(f"📦  Installing {len(missing)} missing package(s): {', '.join(missing)}", file=sys.stderr)
    print("    (This only happens once.)\n", file=sys.stderr)

    def _pip_install(extra_flags: list[str]) -> bool:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *extra_flags, *missing],
            capture_output=True,
        )
        return result.returncode == 0

    if _pip_install([]):
        print("✅  All packages installed.\n", file=sys.stderr)
        return

    print("    Standard install blocked (externally-managed environment).", file=sys.stderr)
    print("    Retrying with --break-system-packages ...\n", file=sys.stderr)
    if _pip_install(["--break-system-packages"]):
        print("✅  All packages installed.\n", file=sys.stderr)
        return

    pkg_str = " ".join(missing)
    print("❌  Auto-install failed. Choose one of these options:\n", file=sys.stderr)
    print(f"  Option A — force install into system Python:", file=sys.stderr)
    print(f"    pip install --break-system-packages {pkg_str}\n", file=sys.stderr)
    print(f"  Option B — use a virtual environment (recommended):", file=sys.stderr)
    print(f"    python3 -m venv .venv && source .venv/bin/activate", file=sys.stderr)
    print(f"    pip install {pkg_str}", file=sys.stderr)
    print(f"    python feature_map.py .\n", file=sys.stderr)
    sys.exit(1)


# ════════════════════════════════════════════════════════════════
# 1. GRAPH BUILDING
# ════════════════════════════════════════════════════════════════

def build_graph(root: Path):
    """
    Call Graphify's Python API directly to build a code knowledge graph.
    Returns (G: nx.Graph, communities: dict[int, list[str]])
    """
    try:
        from graphify.extract import collect_files
        from graphify.extract import extract as gfy_extract
        from graphify.build import build as gfy_build
        from graphify.cluster import cluster as gfy_cluster
    except ImportError:
        print("❌  graphify not installed.", file=sys.stderr)
        print("    Run: pip install graphifyy", file=sys.stderr)
        sys.exit(1)

    print(f"  📂 Scanning {root} ...", file=sys.stderr)
    files = collect_files(root)
    print(f"  📄 {len(files)} files found", file=sys.stderr)

    print("  🔗 Extracting code structure (AST + batch) ...", file=sys.stderr)
    extraction = gfy_extract(files, cache_root=root)
    nodes_found = len(extraction.get("nodes", []))
    if nodes_found == 0:
        print("error: AST extraction produced no nodes.", file=sys.stderr)
        sys.exit(1)

    print(f"  📊 Building graph from {nodes_found} nodes ...", file=sys.stderr)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        G = gfy_build([extraction], directed=True, root=root)

    print("  🌐 Community detection (Leiden) ...", file=sys.stderr)
    communities = gfy_cluster(G)

    print(f"  ✅ {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(communities)} communities", file=sys.stderr)
    return G, communities


# ════════════════════════════════════════════════════════════════
# 2. AST ENRICHMENT
# ════════════════════════════════════════════════════════════════

def _loc_to_line(loc: str) -> int | None:
    m = re.match(r"L(\d+)", str(loc or ""))
    return int(m.group(1)) if m else None


def _enrich_python(path: Path, nodes: list[dict]) -> dict[str, dict]:
    try:
        import tree_sitter_python as tspy
        from tree_sitter import Language, Parser
    except ImportError:
        return {}
    try:
        src = path.read_bytes()
        lang = Language(tspy.language())
        tree = Parser(lang).parse(src)
    except Exception:
        return {}

    by_line = {_loc_to_line(n.get("source_location", "")): n
                for n in nodes if _loc_to_line(n.get("source_location", ""))}

    result: dict[str, dict] = {}

    def _docstring(body_node) -> str:
        if not body_node:
            return ""
        for ch in body_node.children:
            if ch.type == "expression_statement" and ch.child_count > 0:
                s = ch.children[0]
                if s.type == "string":
                    raw = src[s.start_byte:s.end_byte].decode(errors="replace")
                    return raw.strip().strip('"""').strip("'''").strip("'\"").strip()[:600]
            break
        return ""

    def walk(node):
        if node.type in ("function_definition", "async_function_definition"):
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            name_n   = node.child_by_field_name("name")
            params_n = node.child_by_field_name("parameters")
            ret_n    = node.child_by_field_name("return_type")
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace")    if name_n   else "?"
            params = src[params_n.start_byte:params_n.end_byte].decode(errors="replace") if params_n else "()"
            ret    = (" -> " + src[ret_n.start_byte:ret_n.end_byte].decode(errors="replace")) if ret_n else ""
            prefix = "async def " if node.type == "async_function_definition" else "def "
            sig    = f"{prefix}{name}{params}{ret}"
            doc    = _docstring(node.child_by_field_name("body"))
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(line_start=sl, line_end=el,
                                             signature=sig, docstring=doc, kind="function")

        elif node.type == "class_definition":
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            name_n = node.child_by_field_name("name")
            sup_n  = node.child_by_field_name("superclasses")
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            bases  = ("(" + src[sup_n.start_byte:sup_n.end_byte].decode(errors="replace") + ")") if sup_n else ""
            doc    = _docstring(node.child_by_field_name("body"))
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(line_start=sl, line_end=el,
                                             signature=f"class {name}{bases}", docstring=doc, kind="class")

        for ch in node.children:
            walk(ch)

    walk(tree.root_node)
    return result


def _enrich_js(path: Path, nodes: list[dict]) -> dict[str, dict]:
    try:
        suf = path.suffix.lower()
        if suf in (".ts", ".tsx"):
            import tree_sitter_typescript as tslang
            from tree_sitter import Language, Parser
            lang = Language(tslang.language_typescript())
        else:
            import tree_sitter_javascript as tslang
            from tree_sitter import Language, Parser
            lang = Language(tslang.language())
    except ImportError:
        return {}
    try:
        src = path.read_bytes()
        tree = Parser(lang).parse(src)
    except Exception:
        return {}

    by_line = {_loc_to_line(n.get("source_location", "")): n
                for n in nodes if _loc_to_line(n.get("source_location", ""))}
    result: dict[str, dict] = {}

    def walk(node):
        if node.type in ("function_declaration", "function_expression",
                          "arrow_function", "method_definition"):
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            name_n   = node.child_by_field_name("name")
            params_n = node.child_by_field_name("parameters") or node.child_by_field_name("formal_parameters")
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "<anonymous>"
            params = src[params_n.start_byte:params_n.end_byte].decode(errors="replace") if params_n else "()"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(line_start=sl, line_end=el,
                                             signature=f"function {name}{params}", docstring="", kind="function")

        elif node.type in ("class_declaration", "class_expression"):
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            name_n = node.child_by_field_name("name")
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(line_start=sl, line_end=el,
                                             signature=f"class {name}", docstring="", kind="class")

        for ch in node.children:
            walk(ch)

    walk(tree.root_node)
    return result


def _enrich_by_estimation(path: Path, nodes: list[dict]) -> dict[str, dict]:
    try:
        total = len(path.read_text(errors="replace").split("\n"))
    except Exception:
        total = 9999
    ordered = sorted(
        [(n, _loc_to_line(n.get("source_location", "L1")) or 1) for n in nodes],
        key=lambda x: x[1],
    )
    result: dict[str, dict] = {}
    for i, (n, sl) in enumerate(ordered):
        el = ordered[i + 1][1] - 1 if i + 1 < len(ordered) else total
        result[n["id"]] = dict(line_start=sl, line_end=max(el, sl),
                               signature=n.get("label", "").strip(), docstring="", kind="unknown")
    return result


_ENRICH_HANDLERS = {
    ".py": _enrich_python,
    ".js": _enrich_js, ".jsx": _enrich_js,
    ".ts": _enrich_js, ".tsx": _enrich_js,
}


def enrich_nodes(G) -> dict[str, dict]:
    """
    Group code nodes by source file, then do one AST parse per file.
    Returns enriched: {node_id → {line_start, line_end, signature, docstring, kind}}
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") == "code" and attrs.get("source_file"):
            by_file[attrs["source_file"]].append({"id": nid, **attrs})

    enriched: dict[str, dict] = {}
    total_nodes = sum(len(v) for v in by_file.values())

    for file_path, nodes in by_file.items():
        p = Path(file_path)
        if not p.exists():
            continue
        handler = _ENRICH_HANDLERS.get(p.suffix.lower())
        res = handler(p, nodes) if handler else {}
        missing = [n for n in nodes if n["id"] not in res]
        if missing:
            res.update(_enrich_by_estimation(p, missing))
        enriched.update(res)

    print(f"  ✅ Enriched {len(enriched)} / {total_nodes} nodes  "
          f"(tree-sitter: {sum(1 for v in enriched.values() if v['kind'] != 'unknown')}  "
          f"estimated: {sum(1 for v in enriched.values() if v['kind'] == 'unknown')})",
          file=sys.stderr)
    return enriched


# ════════════════════════════════════════════════════════════════
# 3. FEATURE ANALYSIS
# ════════════════════════════════════════════════════════════════

def _entry_point_score(G, nid: str, member_set: set[str]) -> float:
    attrs = G.nodes[nid]
    label = attrs.get("label", "").strip("()").lstrip(".")
    fpath = attrs.get("source_file", "").lower()
    score = 0.0
    score += sum(1 for p in G.predecessors(nid) if p not in member_set) * 4.0
    if label and not label.startswith("_"):
        score += 2.0
    if any(k in fpath for k in ("route", "controller", "handler", "view", "api", "endpoint", "router", "main")):
        score += 3.0
    score += sum(1 for s in G.successors(nid) if s in member_set) * 0.5
    if any(k in label.lower() for k in ("_helper", "_util", "_format", "_parse", "_validate")):
        score -= 1.0
    return score


def _trace_chain(G, start: str, max_depth: int = 6) -> list[dict]:
    visited: set[str] = set()
    chain: list[dict] = []
    queue = [(start, 0, "ENTRY", None)]
    while queue:
        nid, depth, conf, parent = queue.pop(0)
        if nid in visited or depth > max_depth:
            continue
        visited.add(nid)
        chain.append(dict(node_id=nid, depth=depth, via_confidence=conf, parent_id=parent))
        if depth < max_depth:
            edges = list(G.out_edges(nid, data=True))
            edges.sort(key=lambda e: {"EXTRACTED": 0, "INFERRED": 1, "AMBIGUOUS": 2}
                                     .get(e[2].get("confidence", "AMBIGUOUS"), 2))
            for _, succ, edata in edges:
                if succ not in visited and edata.get("relation") == "calls":
                    queue.append((succ, depth + 1, edata.get("confidence", "AMBIGUOUS"), nid))
    return chain


def _primary_files(G, member_ids: list[str]) -> list[str]:
    cnt: dict[str, int] = defaultdict(int)
    for nid in member_ids:
        f = G.nodes[nid].get("source_file", "")
        if f:
            cnt[f] += 1
    return sorted(cnt, key=lambda f: -cnt[f])[:5]


def _feature_name(G, member_ids: list[str], entry_ids: list[str], cid: int) -> str:
    skip = {"src", "lib", "app", "main", "core", ".", "__init__", "pkg", "internal"}
    dirs = []
    for fp in _primary_files(G, member_ids)[:2]:
        parts = [p for p in Path(fp).parts[:-1] if p not in skip and not p.startswith(".")]
        dirs.extend(parts[-2:])
    dir_label = "/".join(dict.fromkeys(dirs))[:40] if dirs else f"module_{cid}"

    if entry_ids:
        ep_label = G.nodes[entry_ids[0]].get("label", "").strip("()").lstrip(".")
        if ep_label and len(ep_label) < 40:
            return f"{dir_label} · {ep_label}" if dir_label else ep_label
    return dir_label or f"Community {cid}"


def analyze_features(G, communities: dict[int, list[str]]) -> list[dict]:
    features = []
    for cid, members in sorted(communities.items()):
        if not members:
            continue
        member_set = set(members)
        scored = sorted(members, key=lambda n: -_entry_point_score(G, n, member_set))
        entries = [n for n in scored[:5] if _entry_point_score(G, n, member_set) >= 0]

        chains: dict[str, list[dict]] = {}
        for ep in entries[:3]:
            ch = _trace_chain(G, ep)
            if len(ch) > 1:
                chains[ep] = ch

        pfiles = _primary_files(G, members)
        name   = _feature_name(G, members, entries, cid)
        features.append(dict(
            id=f"feature_{cid}",
            community_id=cid,
            name=name,
            member_ids=members,
            entry_point_ids=entries,
            call_chains=chains,
            primary_files=pfiles,
            member_count=len(members),
        ))

    features.sort(key=lambda f: -f["member_count"])
    print(f"  ✅ {len(features)} feature modules identified", file=sys.stderr)
    return features


# ════════════════════════════════════════════════════════════════
# 4. HTML GENERATION  (English UI, single-file data-embedded)
# ════════════════════════════════════════════════════════════════

def _mermaid(G, chain: list[dict]) -> str:
    safe = lambda s: re.sub(r"[^a-zA-Z0-9]", "_", s)
    label = lambda nid: G.nodes[nid].get("label", nid).replace('"', "'").strip("()")[:30]
    lines = ["graph TD"]
    seen: set[str] = set()
    for item in chain:
        sid = safe(item["node_id"])
        if sid not in seen:
            lbl = label(item["node_id"])
            shape = f"(({lbl}))" if item["depth"] == 0 else f'["{lbl}"]'
            lines.append(f"  {sid}{shape}")
            seen.add(sid)
    for item in chain:
        if item.get("parent_id"):
            src = safe(item["parent_id"])
            tgt = safe(item["node_id"])
            arrow = "-->" if item.get("via_confidence") == "EXTRACTED" else "-.->"
            lines.append(f"  {src} {arrow} {tgt}")
    return "\n".join(lines)


def _build_page_data(features: list[dict], G, enriched: dict, root: Path) -> dict:
    def rel(fp: str) -> str:
        try:
            return str(Path(fp).relative_to(root))
        except Exception:
            return fp

    all_funcs: dict[str, dict] = {}
    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") != "code":
            continue
        rich = enriched.get(nid, {})
        all_funcs[nid] = dict(
            id=nid,
            label=attrs.get("label", nid),
            file_path=rel(attrs.get("source_file", "")),
            line_start=rich.get("line_start"),
            line_end=rich.get("line_end"),
            signature=rich.get("signature", attrs.get("label", "")),
            docstring=rich.get("docstring", ""),
            kind=rich.get("kind", "unknown"),
        )

    page_features = []
    for f in features:
        ep_set = set(f["entry_point_ids"])
        members = [all_funcs[m] for m in f["member_ids"] if m in all_funcs]
        members.sort(key=lambda m: (
            0 if m["id"] in ep_set else 1,
            m["file_path"],
            m["line_start"] or 0,
        ))
        diagrams = {ep: _mermaid(G, ch) for ep, ch in f["call_chains"].items()}
        page_features.append(dict(
            id=f["id"],
            name=f["name"],
            member_count=f["member_count"],
            primary_files=[rel(fp) for fp in f["primary_files"]],
            entry_point_ids=f["entry_point_ids"],
            members=members,
            diagrams=diagrams,
        ))

    return dict(
        repo_name=root.name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        features=page_features,
        total_functions=len(all_funcs),
        total_features=len(features),
    )


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
.kbadge.unknown{background:rgba(85,85,85,.2);color:var(--text3)}
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
    <div id="welcome"><h2>Select a feature module from the sidebar</h2><p>Feature modules auto-detected from source, with call chains and function tables.</p></div>
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
      <div class="ep-sig">${esc(m.signature||m.label)}</div>
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
    <td><span class="fn ${epSet.has(m.id)?'ep':''}">${esc(m.label)}</span></td>
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


def generate_html(features: list[dict], G, enriched: dict, root: Path, out: Path) -> None:
    data = _build_page_data(features, G, enriched, root)
    html = _HTML.replace("__DATA_PLACEHOLDER__", json.dumps(data, ensure_ascii=False))
    out.write_text(html, encoding="utf-8")
    kb = out.stat().st_size // 1024
    print(f"  ✅ functionality.html  ({kb} KB)  →  {out}", file=sys.stderr)


# ════════════════════════════════════════════════════════════════
# 5. LLM INDEX
# ════════════════════════════════════════════════════════════════

def generate_llm_index(features: list[dict], G, enriched: dict, root: Path, out: Path) -> None:
    def rel(fp: str) -> str:
        try:
            return str(Path(fp).relative_to(root))
        except Exception:
            return fp

    node_to_feat: dict[str, str] = {}
    for f in features:
        for mid in f["member_ids"]:
            node_to_feat[mid] = f["name"]

    feat_idx: dict[str, dict] = {}
    for f in features:
        summary = ""
        for ep_id, chain in f["call_chains"].items():
            labels = [G.nodes[item["node_id"]].get("label", "").strip("()") for item in chain[:6]]
            summary = " → ".join(labels)
            break
        feat_idx[f["name"]] = dict(
            feature_id=f["id"],
            entry_point_ids=f["entry_point_ids"],
            all_function_ids=f["member_ids"],
            primary_files=[rel(fp) for fp in f["primary_files"]],
            call_chain_summary=summary,
            function_count=f["member_count"],
        )

    func_idx: dict[str, dict] = {}
    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") != "code":
            continue
        rich = enriched.get(nid, {})
        callees = [v for _, v, ed in G.out_edges(nid, data=True) if ed.get("relation") == "calls"]
        callers = [u for u, _, ed in G.in_edges(nid, data=True)  if ed.get("relation") == "calls"]
        func_idx[nid] = dict(
            label=attrs.get("label", nid),
            kind=rich.get("kind", "unknown"),
            file_path=rel(attrs.get("source_file", "")),
            line_start=rich.get("line_start"),
            line_end=rich.get("line_end"),
            signature=rich.get("signature", attrs.get("label", "")),
            docstring=rich.get("docstring", ""),
            direct_callees=callees,
            direct_callers=callers,
            feature_name=node_to_feat.get(nid, ""),
        )

    file_idx: dict[str, dict] = {}
    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") != "code" or not attrs.get("source_file"):
            continue
        fp = rel(attrs["source_file"])
        if fp not in file_idx:
            file_idx[fp] = dict(functions=[], classes=[])
        kind = enriched.get(nid, {}).get("kind", "unknown")
        file_idx[fp]["classes" if kind == "class" else "functions"].append(nid)

    index = dict(
        version="2.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_repo=str(root),
        how_to_use=(
            "Step 1: find feature in `features` by name → get entry_point_ids\n"
            "Step 2: look up functions[entry_point_id] → file_path + line_start + line_end\n"
            "Step 3: read that file range to get the full code\n"
            "Step 4: follow direct_callees recursively to trace the full chain\n"
            "Tip: call_chain_summary gives a quick linear view of the main path\n"
            "Confidence: EXTRACTED=AST-confirmed  INFERRED=same-file inferred  AMBIGUOUS=text-matched"
        ),
        statistics=dict(
            total_features=len(features),
            total_functions=len(func_idx),
            total_files=len(file_idx),
        ),
        features=feat_idx,
        functions=func_idx,
        files=file_idx,
    )
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    kb = out.stat().st_size // 1024
    print(f"  ✅ FUNCTION_INDEX.json ({kb} KB)  →  {out}", file=sys.stderr)


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main() -> None:
    _ensure_deps()

    parser = argparse.ArgumentParser(
        prog="feature_map",
        description="Codebase Feature Map Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python feature_map.py .
          python feature_map.py /path/to/repo -o ./out
          python feature_map.py . --no-html
          python feature_map.py . --no-json
        """),
    )
    parser.add_argument("root", nargs="?", default=".", help="Directory to analyze (default: .)")
    parser.add_argument("-o", "--output", default="feature-map-out",
                        help="Output directory (default: ./feature-map-out in current working dir)")
    parser.add_argument("--no-html",  action="store_true", help="Skip HTML output")
    parser.add_argument("--no-json",  action="store_true", help="Skip JSON index output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    # Output is relative to CWD, not the target repo
    out  = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    if not root.is_dir():
        print(f"❌  '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    print(f"\n🗺️  Feature Map Generator", file=sys.stderr)
    print(f"   Target : {root}", file=sys.stderr)
    print(f"   Output : {out.resolve()}\n", file=sys.stderr)

    print("── Step 1/4  Building code graph ───────────────────────────", file=sys.stderr)
    G, communities = build_graph(root)

    print("\n── Step 2/4  AST enrichment (line ranges / signatures) ─────", file=sys.stderr)
    enriched = enrich_nodes(G)

    print("\n── Step 3/4  Feature analysis ──────────────────────────────", file=sys.stderr)
    features = analyze_features(G, communities)

    print("\n── Step 4/4  Generating outputs ────────────────────────────", file=sys.stderr)
    html_path = None
    json_path = None
    if not args.no_html:
        html_path = out / "functionality.html"
        generate_html(features, G, enriched, root, html_path)
    if not args.no_json:
        json_path = out / "FUNCTION_INDEX.json"
        generate_llm_index(features, G, enriched, root, json_path)

    print(f"\n✅  Done!  Results in: {out.resolve()}/", file=sys.stderr)
    if html_path:
        print(f"   🌐  functionality.html   — open in any browser", file=sys.stderr)
    if json_path:
        print(f"   📋  FUNCTION_INDEX.json  — feed to Claude for O(1) code navigation", file=sys.stderr)
    print(file=sys.stderr)

    # Structured summary to stdout — for Claude Code skill consumption
    summary = {
        "features": len(features),
        "functions": G.number_of_nodes(),
        "output_dir": str(out.resolve()),
        "html_path": str(html_path.resolve()) if html_path else None,
        "json_path": str(json_path.resolve()) if json_path else None,
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
