#!/usr/bin/env python3
"""
synth_index.py — Code Index Builder

Scans a codebase using graphify + tree-sitter to produce FUNCTION_INDEX.json:
a structured, LLM-ready index of features, functions, data models, and call chains.

Pipeline:
  1. graphify   — AST extraction + graph construction + Leiden community detection
  2. tree-sitter — enrichment: signatures, docstrings, line ranges, entry-point kinds
  3. Feature analysis — community clustering, call-chain tracing, data-model detection
  4. Output — FUNCTION_INDEX.json + graph.json + graphify-cache/

Usage:
  python synth_index.py .                      # analyze current directory
  python synth_index.py /path/to/repo          # analyze specific directory
  python synth_index.py . -o ./my-analysis     # custom output directory
  python synth_index.py . --force              # force rebuild

Output directory (default: {repo_root}/synth-out/):
  FUNCTION_INDEX.json    — primary LLM-ready index (consumed by /feature-map, /synth-card)
  graph.json             — graphify graph export (for external tooling)
  graphify-cache/        — graphify AST extraction cache (speeds up incremental rebuilds)

All progress output → stderr
JSON summary line    → stdout  (for skill chaining)
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
# 0. DEPENDENCY BOOTSTRAP
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
    "graphifyy":              "graphify",
    "tree-sitter":            "tree_sitter",
    "tree-sitter-python":     "tree_sitter_python",
    "tree-sitter-javascript": "tree_sitter_javascript",
    "tree-sitter-typescript": "tree_sitter_typescript",
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
    print("    Standard install blocked. Retrying with --break-system-packages ...\n", file=sys.stderr)
    if _pip_install(["--break-system-packages"]):
        print("✅  All packages installed.\n", file=sys.stderr)
        return

    pkg_str = " ".join(missing)
    print("❌  Auto-install failed. Run one of:\n", file=sys.stderr)
    print(f"  pip install --break-system-packages {pkg_str}", file=sys.stderr)
    print(f"  # or in a venv:", file=sys.stderr)
    print(f"  python3 -m venv .venv && source .venv/bin/activate && pip install {pkg_str}", file=sys.stderr)
    sys.exit(1)


# ════════════════════════════════════════════════════════════════
# CONSTANTS & SHARED HELPERS
# ════════════════════════════════════════════════════════════════

_CODE_FILE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".go", ".rs", ".java", ".rb", ".php",
    ".cpp", ".c", ".h", ".cs", ".swift", ".kt", ".scala",
    ".ex", ".exs",
})

_ROUTE_RE     = re.compile(r"@\w[\w.]*\.(get|post|put|delete|patch|route|websocket)\s*[(\"]", re.I)
_CLI_RE       = re.compile(r"@(click|app|cli|typer|router)\.(command|group|callback)\s*[(\"]", re.I)
_LIFECYCLE_RE = re.compile(r"@(app|router)\.(on_event|startup|shutdown|on_startup|on_shutdown)\s*[(\"]", re.I)
_TASK_RE      = re.compile(r"@(celery|task|shared_task|dramatiq)\b", re.I)
_TEST_RE      = re.compile(r"@pytest\.|@unittest\.", re.I)

_SCHEMA_BASES = frozenset({
    "BaseModel", "TypedDict", "Schema", "BaseSchema",
    "SQLModel", "DeclarativeBase", "Base",
})

_MIN_CODE_NODES = 2   # communities with fewer code nodes are dropped


def _is_code_file(path_str: str) -> bool:
    return Path(path_str).suffix.lower() in _CODE_FILE_SUFFIXES


def _classify_entry_kind(decorators: list[str], name: str) -> str:
    """Return semantic entry-point kind from decorator list + function name."""
    for dec in decorators:
        if _ROUTE_RE.search(dec):      return "ROUTE"
        if _CLI_RE.search(dec):        return "CLI_COMMAND"
        if _LIFECYCLE_RE.search(dec):  return "EVENT_HANDLER"
        if _TASK_RE.search(dec):       return "TASK"
        if _TEST_RE.search(dec):       return "TEST"
    if name in ("main", "__main__"):
        return "CLI_ENTRY"
    return ""


# ════════════════════════════════════════════════════════════════
# 1. GRAPH BUILDING
# ════════════════════════════════════════════════════════════════

def build_graph(root: Path, output_dir: Path):
    """
    Run graphify pipeline: collect → extract → build graph → cluster communities.
    Saves graph.json and uses graphify-cache/ inside output_dir.
    Returns (G: nx.DiGraph, communities: dict[int, list[str]])
    """
    try:
        from graphify.extract import collect_files
        from graphify.extract import extract as gfy_extract
        from graphify.build import build as gfy_build
        from graphify.cluster import cluster as gfy_cluster
        from graphify.export import to_json as gfy_to_json
    except ImportError:
        print("❌  graphify not installed.  Run: pip install graphifyy", file=sys.stderr)
        sys.exit(1)

    cache_dir = output_dir / "graphify-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"  📂 Scanning {root} ...", file=sys.stderr)
    files = collect_files(root)
    print(f"  📄 {len(files)} files found", file=sys.stderr)

    print("  🔗 Extracting code structure (AST + batch) ...", file=sys.stderr)
    extraction = gfy_extract(files, cache_root=cache_dir)
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

    # Persist graph.json — callers can control the path via output_dir
    graph_path = output_dir / "graph.json"
    gfy_to_json(G, communities, str(graph_path), force=True)

    print(f"  ✅ {G.number_of_nodes()} nodes · {G.number_of_edges()} edges "
          f"· {len(communities)} communities", file=sys.stderr)
    print(f"  📄 graph.json → {graph_path}", file=sys.stderr)
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
        src  = path.read_bytes()
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

    def _decorators(node) -> list[str]:
        p = node.parent
        if p and p.type == "decorated_definition":
            return [
                src[ch.start_byte:ch.end_byte].decode(errors="replace").strip()
                for ch in p.children if ch.type == "decorator"
            ]
        return []

    def walk(node):
        if node.type in ("function_definition", "async_function_definition"):
            sl       = node.start_point[0] + 1
            el       = node.end_point[0] + 1
            name_n   = node.child_by_field_name("name")
            params_n = node.child_by_field_name("parameters")
            ret_n    = node.child_by_field_name("return_type")
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace")    if name_n   else "?"
            params = src[params_n.start_byte:params_n.end_byte].decode(errors="replace") if params_n else "()"
            ret    = (" -> " + src[ret_n.start_byte:ret_n.end_byte].decode(errors="replace")) if ret_n else ""
            prefix = "async def " if node.type == "async_function_definition" else "def "
            sig    = f"{prefix}{name}{params}{ret}"
            doc    = _docstring(node.child_by_field_name("body"))
            decs   = _decorators(node)
            ekind  = _classify_entry_kind(decs, name)
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=sig, docstring=doc,
                    kind="function", decorators=decs, entry_kind=ekind,
                )

        elif node.type == "class_definition":
            sl         = node.start_point[0] + 1
            el         = node.end_point[0] + 1
            name_n     = node.child_by_field_name("name")
            sup_n      = node.child_by_field_name("superclasses")
            name       = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            bases_text = src[sup_n.start_byte:sup_n.end_byte].decode(errors="replace") if sup_n else ""
            bases      = f"({bases_text})" if bases_text else ""
            doc        = _docstring(node.child_by_field_name("body"))
            decs       = _decorators(node)
            if any("dataclass" in d for d in decs):
                ckind = "dataclass"
            elif any(b in bases_text for b in _SCHEMA_BASES):
                ckind = "schema"
            else:
                ckind = "class"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=f"class {name}{bases}", docstring=doc,
                    kind=ckind, decorators=decs, entry_kind="",
                )

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
        src  = path.read_bytes()
        tree = Parser(lang).parse(src)
    except Exception:
        return {}

    by_line = {_loc_to_line(n.get("source_location", "")): n
               for n in nodes if _loc_to_line(n.get("source_location", ""))}
    result: dict[str, dict] = {}

    def _is_exported(node) -> bool:
        p = node.parent
        return bool(p and p.type in ("export_statement", "export_declaration"))

    def walk(node):
        if node.type in ("function_declaration", "function_expression",
                          "arrow_function", "method_definition"):
            sl       = node.start_point[0] + 1
            el       = node.end_point[0] + 1
            name_n   = node.child_by_field_name("name")
            params_n = (node.child_by_field_name("parameters")
                        or node.child_by_field_name("formal_parameters"))
            name   = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "<anonymous>"
            params = src[params_n.start_byte:params_n.end_byte].decode(errors="replace") if params_n else "()"
            ekind  = "EXPORT" if _is_exported(node) else ""
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=f"function {name}{params}", docstring="",
                    kind="function", decorators=[], entry_kind=ekind,
                )

        elif node.type in ("class_declaration", "class_expression"):
            sl      = node.start_point[0] + 1
            el      = node.end_point[0] + 1
            name_n  = node.child_by_field_name("name")
            name    = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=f"class {name}", docstring="",
                    kind="class", decorators=[], entry_kind="",
                )

        elif node.type == "interface_declaration":
            sl      = node.start_point[0] + 1
            el      = node.end_point[0] + 1
            name_n  = node.child_by_field_name("name")
            name    = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=f"interface {name}", docstring="",
                    kind="interface", decorators=[], entry_kind="",
                )

        elif node.type == "type_alias_declaration":
            sl      = node.start_point[0] + 1
            el      = node.end_point[0] + 1
            name_n  = node.child_by_field_name("name")
            name    = src[name_n.start_byte:name_n.end_byte].decode(errors="replace") if name_n else "?"
            matched = by_line.get(sl)
            if matched:
                result[matched["id"]] = dict(
                    line_start=sl, line_end=el,
                    signature=f"type {name}", docstring="",
                    kind="type", decorators=[], entry_kind="",
                )

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
        result[n["id"]] = dict(
            line_start=sl, line_end=max(el, sl),
            signature=n.get("label", "").strip(), docstring="",
            kind="unknown", decorators=[], entry_kind="",
        )
    return result


_ENRICH_HANDLERS = {
    ".py":  _enrich_python,
    ".js":  _enrich_js, ".jsx": _enrich_js,
    ".ts":  _enrich_js, ".tsx": _enrich_js,
}


def enrich_nodes(G) -> dict[str, dict]:
    """
    Group code nodes by source file, do one AST parse per file.
    Returns enriched: {node_id → {line_start, line_end, signature, docstring, kind, ...}}
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
        res     = handler(p, nodes) if handler else {}
        missing = [n for n in nodes if n["id"] not in res]
        if missing:
            res.update(_enrich_by_estimation(p, missing))
        enriched.update(res)

    ts_count = sum(1 for v in enriched.values() if v["kind"] != "unknown")
    print(f"  ✅ Enriched {len(enriched)} / {total_nodes} nodes  "
          f"(tree-sitter: {ts_count}  estimated: {len(enriched) - ts_count})",
          file=sys.stderr)
    return enriched


# ════════════════════════════════════════════════════════════════
# 3. FEATURE ANALYSIS
# ════════════════════════════════════════════════════════════════

def _entry_point_score(G, nid: str, member_set: set[str], enriched: dict) -> float:
    attrs = G.nodes[nid]
    label = attrs.get("label", "").strip("()").lstrip(".")
    fpath = attrs.get("source_file", "").lower()
    rich  = enriched.get(nid, {})
    score = 0.0
    ekind = rich.get("entry_kind", "")
    if ekind == "ROUTE":         score += 20.0
    if ekind == "CLI_COMMAND":   score += 18.0
    if ekind == "CLI_ENTRY":     score += 15.0
    if ekind == "EVENT_HANDLER": score += 12.0
    if ekind == "EXPORT":        score += 8.0
    if ekind == "TASK":          score += 6.0
    if ekind == "TEST":          score -= 5.0
    score += sum(1 for p in G.predecessors(nid) if p not in member_set) * 4.0
    if label and not label.startswith("_"):
        score += 2.0
    if any(k in fpath for k in ("route", "controller", "handler", "view",
                                 "api", "endpoint", "router", "main")):
        score += 3.0
    score += sum(1 for s in G.successors(nid) if s in member_set) * 0.5
    if any(k in label.lower() for k in ("_helper", "_util", "_format", "_parse", "_validate")):
        score -= 1.0
    return score


def _trace_chain(G, start: str, max_depth: int = 6) -> list[dict]:
    visited: set[str] = set()
    chain:   list[dict] = []
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


def _mermaid(G, chain: list[dict]) -> str:
    safe  = lambda s: re.sub(r"[^a-zA-Z0-9]", "_", s)
    label = lambda nid: G.nodes[nid].get("label", nid).replace('"', "'").strip("()")[:30]
    lines = ["graph TD"]
    seen: set[str] = set()
    for item in chain:
        sid = safe(item["node_id"])
        if sid not in seen:
            lbl   = label(item["node_id"])
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


def analyze_features(G, communities: dict[int, list[str]], enriched: dict) -> list[dict]:
    features = []
    skipped  = 0
    for cid, members in sorted(communities.items()):
        if not members:
            continue
        code_members = [
            m for m in members
            if G.nodes[m].get("file_type") == "code"
            and _is_code_file(G.nodes[m].get("source_file", ""))
        ]
        if len(code_members) < _MIN_CODE_NODES:
            skipped += 1
            continue
        members = code_members

        member_set = set(members)
        scored  = sorted(members, key=lambda n: -_entry_point_score(G, n, member_set, enriched))
        entries = [n for n in scored[:5] if _entry_point_score(G, n, member_set, enriched) >= 0]

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
    print(f"  ✅ {len(features)} feature modules identified  "
          f"({skipped} non-code communities skipped)", file=sys.stderr)
    return features


# ════════════════════════════════════════════════════════════════
# 4. INDEX GENERATION
# ════════════════════════════════════════════════════════════════

def generate_index(features: list[dict], G, enriched: dict,
                   root: Path, output_dir: Path) -> tuple[Path, dict]:
    def rel(fp: str) -> str:
        try:
            return str(Path(fp).relative_to(root))
        except Exception:
            return fp

    _DATA_MODEL_KINDS = frozenset({"dataclass", "schema", "interface", "type"})

    node_to_feat: dict[str, str] = {}
    for f in features:
        for mid in f["member_ids"]:
            node_to_feat[mid] = f["name"]

    # ── features section (includes pre-rendered Mermaid diagrams) ────────────
    feat_idx: dict[str, dict] = {}
    for f in features:
        summary  = ""
        diagrams: dict[str, str] = {}
        for ep_id, chain in f["call_chains"].items():
            labels = [G.nodes[item["node_id"]].get("label", "").strip("()") for item in chain[:6]]
            if not summary:
                summary = " → ".join(labels)
            diagrams[ep_id] = _mermaid(G, chain)
        feat_idx[f["name"]] = dict(
            feature_id=f["id"],
            entry_point_ids=f["entry_point_ids"],
            all_function_ids=f["member_ids"],
            primary_files=[rel(fp) for fp in f["primary_files"]],
            call_chain_summary=summary,
            function_count=f["member_count"],
            diagrams=diagrams,
        )

    # ── functions + data_models sections ─────────────────────────────────────
    func_idx:       dict[str, dict] = {}
    data_model_idx: dict[str, dict] = {}

    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") != "code":
            continue
        if not _is_code_file(attrs.get("source_file", "")):
            continue
        rich    = enriched.get(nid, {})
        callees = [v for _, v, ed in G.out_edges(nid, data=True) if ed.get("relation") == "calls"]
        callers = [u for u, _, ed in G.in_edges(nid, data=True)  if ed.get("relation") == "calls"]
        kind    = rich.get("kind", "unknown")
        entry   = dict(
            label=attrs.get("label", nid),
            kind=kind,
            entry_kind=rich.get("entry_kind", ""),
            file_path=rel(attrs.get("source_file", "")),
            line_start=rich.get("line_start"),
            line_end=rich.get("line_end"),
            signature=rich.get("signature", attrs.get("label", "")),
            docstring=rich.get("docstring", ""),
            direct_callees=callees,
            direct_callers=callers,
            feature_name=node_to_feat.get(nid, ""),
        )
        func_idx[nid] = entry
        if kind in _DATA_MODEL_KINDS:
            label = attrs.get("label", nid).strip("()")
            data_model_idx[label] = dict(
                node_id=nid, kind=kind,
                file_path=entry["file_path"],
                line_start=entry["line_start"],
                line_end=entry["line_end"],
                signature=entry["signature"],
                docstring=entry["docstring"],
                feature_name=entry["feature_name"],
            )

    # ── files section ─────────────────────────────────────────────────────────
    file_idx: dict[str, dict] = {}
    for nid, attrs in G.nodes(data=True):
        if attrs.get("file_type") != "code" or not attrs.get("source_file"):
            continue
        if not _is_code_file(attrs.get("source_file", "")):
            continue
        fp   = rel(attrs["source_file"])
        kind = enriched.get(nid, {}).get("kind", "unknown")
        if fp not in file_idx:
            file_idx[fp] = dict(functions=[], classes=[], data_models=[])
        if kind in _DATA_MODEL_KINDS:
            file_idx[fp]["data_models"].append(nid)
        elif kind == "class":
            file_idx[fp]["classes"].append(nid)
        else:
            file_idx[fp]["functions"].append(nid)

    index = dict(
        version="3.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_repo=str(root),
        how_to_use=(
            "Step 1: find feature in `features` by name → get entry_point_ids\n"
            "Step 2: look up functions[entry_point_id] → file_path + line_start + line_end\n"
            "Step 3: read that file range to get the full code\n"
            "Step 4: follow direct_callees recursively to trace the full chain\n"
            "Tip: entry_kind=ROUTE/CLI_COMMAND/EVENT_HANDLER marks user-facing entry points\n"
            "Tip: data_models lists all dataclasses, Pydantic models, TS interfaces\n"
            "Tip: features[name].diagrams has pre-rendered Mermaid call-chain strings\n"
            "Confidence: EXTRACTED=AST-confirmed  INFERRED=same-file  AMBIGUOUS=text-matched"
        ),
        statistics=dict(
            total_features=len(features),
            total_functions=len(func_idx),
            total_data_models=len(data_model_idx),
            total_files=len(file_idx),
        ),
        features=feat_idx,
        functions=func_idx,
        data_models=data_model_idx,
        files=file_idx,
    )

    index_path = output_dir / "FUNCTION_INDEX.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    kb = index_path.stat().st_size // 1024
    print(f"  ✅ FUNCTION_INDEX.json ({kb} KB) → {index_path}", file=sys.stderr)
    return index_path, index


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main() -> None:
    _ensure_deps()

    parser = argparse.ArgumentParser(
        prog="synth_index",
        description="Code Index Builder — produces FUNCTION_INDEX.json for LLM navigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python synth_index.py .
          python synth_index.py /path/to/repo
          python synth_index.py . -o ./my-analysis
          python synth_index.py . --force
        """),
    )
    parser.add_argument("root",     nargs="?", default=".", help="Repository root (default: .)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: {repo_root}/synth-out/)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Rebuild even if index already exists")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"❌  '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).resolve() if args.output else root / "synth-out"
    output_dir.mkdir(parents=True, exist_ok=True)

    index_path = output_dir / "FUNCTION_INDEX.json"

    # Short-circuit if already fresh
    if index_path.exists() and not args.force:
        print(f"✓ Index already exists: {index_path}", file=sys.stderr)
        print("  Pass --force to rebuild.", file=sys.stderr)
        data  = json.loads(index_path.read_text(encoding="utf-8"))
        stats = data.get("statistics", {})
        print(json.dumps({
            "status":       "exists",
            "repo_root":    str(root),
            "output_dir":   str(output_dir),
            "index_path":   str(index_path),
            "features":     stats.get("total_features", 0),
            "functions":    stats.get("total_functions", 0),
            "data_models":  stats.get("total_data_models", 0),
            "generated_at": data.get("generated_at", ""),
        }))
        return

    print(f"\n🔍  Synth Index Builder", file=sys.stderr)
    print(f"   Target : {root}", file=sys.stderr)
    print(f"   Output : {output_dir}\n", file=sys.stderr)

    print("── Step 1/3  Building code graph ───────────────────────────", file=sys.stderr)
    G, communities = build_graph(root, output_dir)

    print("\n── Step 2/3  AST enrichment (signatures / docstrings) ──────", file=sys.stderr)
    enriched = enrich_nodes(G)

    print("\n── Step 3/3  Feature analysis + index generation ───────────", file=sys.stderr)
    features              = analyze_features(G, communities, enriched)
    index_path, index     = generate_index(features, G, enriched, root, output_dir)

    print(f"\n✅  Done!  Output: {output_dir}/", file=sys.stderr)
    print(f"   📋  FUNCTION_INDEX.json  — LLM-ready code index", file=sys.stderr)
    print(f"   📄  graph.json           — graphify graph export", file=sys.stderr)
    print(f"   📁  graphify-cache/      — AST extraction cache", file=sys.stderr)
    print(file=sys.stderr)

    stats = index.get("statistics", {})
    print(json.dumps({
        "status":       "ok",
        "repo_root":    str(root),
        "output_dir":   str(output_dir),
        "index_path":   str(index_path),
        "features":     stats.get("total_features", 0),
        "functions":    stats.get("total_functions", 0),
        "data_models":  stats.get("total_data_models", 0),
        "generated_at": index.get("generated_at", ""),
    }))


if __name__ == "__main__":
    main()
