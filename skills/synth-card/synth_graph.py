#!/usr/bin/env python3
"""synth_graph.py — Synth Graph Tool for the /synth-card Claude Code skill.

Reads FUNCTION_INDEX.json produced by /synth-index. No graphify dependency.

Usage:
    python3 synth_graph.py graph-root  [PATH]
    python3 synth_graph.py graph-list  [PATH] [--json]
    python3 synth_graph.py graph-query KEYWORD [--path PATH] [--json] [--limit N]
    python3 synth_graph.py card-data   [PATH] [--feature TERM] [--module ID] [--limit N]
    python3 synth_graph.py version
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERSION = "0.5.0"

# Source-code file extensions (kept for potential filtering in card-data)
_CODE_FILE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".go", ".rs", ".java", ".rb", ".php",
    ".cpp", ".c", ".h", ".cs", ".swift", ".kt", ".scala",
    ".ex", ".exs",
})


# ---------------------------------------------------------------------------
# FUNCTION_INDEX loader
# ---------------------------------------------------------------------------

def _load_function_index(repo_root: Path, index_path: Path | None = None) -> dict:
    """
    Load FUNCTION_INDEX.json. Search order:
      1. Explicit path (if provided)
      2. {repo_root}/synth-out/FUNCTION_INDEX.json        (canonical)
      3. {repo_root}/feature-map-out/FUNCTION_INDEX.json  (legacy fallback)
    Returns {} if not found or mismatched.
    """
    if index_path and index_path.exists():
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    candidates = [
        repo_root / "synth-out" / "FUNCTION_INDEX.json",
        repo_root / "feature-map-out" / "FUNCTION_INDEX.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            idx = json.loads(path.read_text(encoding="utf-8"))
            src = idx.get("source_repo", "")
            if src and Path(src).resolve() != repo_root.resolve():
                continue
            return idx
        except Exception:
            pass
    return {}


def _index_path_for(repo_root: Path) -> Path:
    """Return the canonical index path (may or may not exist)."""
    canonical = repo_root / "synth-out" / "FUNCTION_INDEX.json"
    if canonical.exists():
        return canonical
    legacy = repo_root / "feature-map-out" / "FUNCTION_INDEX.json"
    if legacy.exists():
        return legacy
    return canonical   # return canonical even if absent (for has_index=false reporting)


# ---------------------------------------------------------------------------
# graph-root
# ---------------------------------------------------------------------------

def cmd_graph_root(args: argparse.Namespace) -> None:
    """Locate the repo root and probe the environment. JSON → stdout."""
    start = Path(args.path).resolve()

    def find_repo_root(p: Path) -> Path:
        for candidate in [p, *p.parents]:
            if (candidate / ".git").exists():
                return candidate
        return p

    root       = find_repo_root(start)
    idx_path   = _index_path_for(root)
    has_index  = idx_path.exists()
    index_mtime: int | None = int(idx_path.stat().st_mtime) if has_index else None

    has_source = (
        any(root.rglob("*.py")) or any(root.rglob("*.ts")) or
        any(root.rglob("*.js")) or any(root.rglob("*.go")) or
        any(root.rglob("*.rs")) or any(root.rglob("*.java"))
    )

    print(json.dumps({
        "repo_root":   str(root),
        "repo_name":   root.name,
        "has_index":   has_index,
        "index_path":  str(idx_path),
        "index_mtime": index_mtime,
        "has_source":  has_source,
        # Legacy aliases kept for backward compatibility
        "has_graph":   has_index,
        "graph_mtime": index_mtime,
    }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# graph-list  (reads from FUNCTION_INDEX features section)
# ---------------------------------------------------------------------------

def cmd_graph_list(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()
    index = _load_function_index(repo_root)

    if not index:
        print(
            f"error: no FUNCTION_INDEX.json found for {repo_root}\n"
            f"Run: /synth-index {repo_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    modules = _features_from_index(index)

    if args.json:
        print(json.dumps(modules, ensure_ascii=False, indent=2))
        return

    repo_name = Path(index.get("source_repo", repo_root.name)).name
    print(f"\n{repo_name} — detected feature modules\n")
    print(f"{'#':<4}  {'Module':<38}  {'Funcs':>5}  {'Primary file':<30}  Entry points")
    print("-" * 110)
    for i, m in enumerate(modules, 1):
        eps = ", ".join(m["sample_nodes"][:2])
        pf  = m["files"][0] if m["files"] else "—"
        print(f"{i:<4}  {m['label']:<38}  {m['size']:>5}  {pf:<30}  {eps}")
    print()


# ---------------------------------------------------------------------------
# graph-query  (searches FUNCTION_INDEX functions section)
# ---------------------------------------------------------------------------

def cmd_graph_query(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()
    index = _load_function_index(repo_root)

    if not index:
        print(f"error: no index found. Run /synth-index {repo_root}", file=sys.stderr)
        sys.exit(1)

    q = args.keyword.lower()
    functions = index.get("functions", {})

    matched = [
        {
            "id":           nid,
            "label":        f.get("label", nid),
            "signature":    f.get("signature", ""),
            "file_path":    f.get("file_path", ""),
            "line_start":   f.get("line_start"),
            "kind":         f.get("kind", ""),
            "entry_kind":   f.get("entry_kind", ""),
            "feature_name": f.get("feature_name", ""),
        }
        for nid, f in functions.items()
        if q in f.get("label", "").lower()
        or q in f.get("file_path", "").lower()
        or q in f.get("signature", "").lower()
        or q in f.get("docstring", "").lower()
    ][:args.limit]

    if args.json:
        print(json.dumps(matched, ensure_ascii=False, indent=2))
        return

    if not matched:
        print(f"No functions matched '{args.keyword}'")
        sys.exit(0)

    print(f"\nSearch results: {args.keyword}\n")
    print(f"{'Signature':<50}  {'Kind':<12}  {'File':<35}  Feature")
    print("-" * 120)
    for n in matched:
        sig = n.get("signature") or n.get("label", "?")
        loc = f"{n.get('file_path','')}"
        if n.get("line_start"):
            loc += f":{n['line_start']}"
        print(f"{sig:<50}  {n.get('kind',''):<12}  {loc:<35}  {n.get('feature_name','')}")
    print(f"\n{len(matched)} match(es) (limit {args.limit})")


# ---------------------------------------------------------------------------
# card-data  (reads FUNCTION_INDEX; enriches nodes directly)
# ---------------------------------------------------------------------------

def cmd_card_data(args: argparse.Namespace) -> None:
    repo_root    = Path(args.path).resolve()
    index        = _load_function_index(repo_root)
    has_index    = bool(index)
    feature_arg: str | None = getattr(args, "feature", None)
    module_arg:  str | None = getattr(args, "module", None)
    limit_nodes: int        = getattr(args, "limit", 40)

    if not has_index:
        # No index — return a helpful error payload
        print(json.dumps({
            "action":    "no_index",
            "message":   f"No FUNCTION_INDEX.json found for {repo_root}. Run /synth-index first.",
            "repo_root": str(repo_root),
        }, ensure_ascii=False, indent=2))
        return

    # Case: no filter → list available modules
    if feature_arg is None and module_arg is None:
        modules = _features_from_index(index)
        print(json.dumps({
            "action":  "choose_module",
            "repo":    Path(index.get("source_repo", repo_root.name)).name,
            "modules": modules,
        }, ensure_ascii=False, indent=2))
        return

    features  = index.get("features", {})
    functions = index.get("functions", {})

    # Resolve target feature
    target_fname: str | None = None
    target_fdata: dict | None = None

    if module_arg is not None:
        # Match by feature_id ("feature_N") or its numeric suffix
        for fname, fdata in features.items():
            fid = fdata.get("feature_id", "")
            if fid == module_arg or fid == f"feature_{module_arg}" \
               or str(fdata.get("community_id", "")) == str(module_arg):
                target_fname, target_fdata = fname, fdata
                break
    else:
        q = feature_arg.lower()
        # Keyword search across feature names and member signatures.
        # best_score starts at 0 so only a real match (score > 0) wins.
        best_score = 0
        for fname, fdata in features.items():
            score = 0
            if q in fname.lower():
                score = 10
            else:
                for fid in fdata.get("all_function_ids", []):
                    func = functions.get(fid, {})
                    if q in func.get("label", "").lower() \
                       or q in func.get("signature", "").lower() \
                       or q in func.get("file_path", "").lower():
                        score = max(score, 5)
            if score > best_score:
                best_score, target_fname, target_fdata = score, fname, fdata

    if target_fdata is None:
        print(json.dumps({
            "action":  "no_match",
            "scope":   feature_arg or module_arg,
            "modules": _features_from_index(index),
        }, ensure_ascii=False, indent=2))
        return

    # Build enriched node list from function index
    member_ids   = target_fdata.get("all_function_ids", [])
    ep_set       = set(target_fdata.get("entry_point_ids", []))
    enriched_nodes = []
    feature_names_seen: set[str] = set()

    for fid in member_ids[:limit_nodes]:
        func = functions.get(fid)
        if not func:
            continue
        node_out: dict = {
            "id":          fid,
            "label":       func.get("label", fid),
            "file_type":   "code",
            "source_file": func.get("file_path", ""),
            "signature":   func.get("signature", ""),
            "docstring":   func.get("docstring", ""),
            "line_start":  func.get("line_start"),
            "line_end":    func.get("line_end"),
            "kind":        func.get("kind", ""),
            "entry_kind":  func.get("entry_kind", ""),
        }
        if func.get("feature_name"):
            feature_names_seen.add(func["feature_name"])
        enriched_nodes.append(node_out)

    # Build call edges from direct_callees
    node_id_set = {n["id"] for n in enriched_nodes}
    edges = [
        {"source": fid, "target": callee, "relation": "calls"}
        for fid in member_ids
        for callee in functions.get(fid, {}).get("direct_callees", [])
        if callee in node_id_set
    ][:80]

    # Pull in relevant data models
    all_dm = index.get("data_models", {})
    relevant_dm = {
        name: dm for name, dm in all_dm.items()
        if not feature_names_seen or dm.get("feature_name", "") in feature_names_seen
    }

    print(json.dumps({
        "action":      "generate_card",
        "repo":        Path(index.get("source_repo", repo_root.name)).name,
        "label":       target_fname,
        "scope":       f"module {module_arg}" if module_arg else f"feature '{feature_arg}'",
        "node_count":  len(enriched_nodes),
        "has_index":   True,
        "nodes":       enriched_nodes,
        "edges":       edges,
        "data_models": relevant_dm,
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Shared helper — build module list from FUNCTION_INDEX features
# ---------------------------------------------------------------------------

def _features_from_index(index: dict) -> list[dict]:
    """Convert FUNCTION_INDEX features section into the graph-list module format."""
    features  = index.get("features", {})
    functions = index.get("functions", {})

    modules = []
    for fname, fdata in features.items():
        # Sample nodes: entry-point signatures or labels
        sample = []
        for fid in fdata.get("entry_point_ids", [])[:4]:
            func = functions.get(fid, {})
            sig  = func.get("signature") or func.get("label", fid)
            if sig:
                sample.append(sig[:60])

        fid = fdata.get("feature_id", "")
        modules.append({
            "community_id": fid[len("feature_"):] if fid.startswith("feature_") else fid,
            "label":        fname,
            "size":         fdata.get("function_count", 0),
            "files":        fdata.get("primary_files", []),
            "entry_point_ids": fdata.get("entry_point_ids", []),
            "sample_nodes": sample,
        })

    return modules


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="synth_graph.py",
        description="Synth Graph Tool — reads FUNCTION_INDEX.json for /synth-card",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # version
    sub.add_parser("version", help="Print version and exit")

    # graph-root
    p_root = sub.add_parser("graph-root", help="Locate repo root + check for index (JSON output)")
    p_root.add_argument("path", nargs="?", default=".", help="Starting path (default: .)")

    # graph-list
    p_list = sub.add_parser("graph-list", help="List detected feature modules")
    p_list.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_list.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")

    # graph-query
    p_query = sub.add_parser("graph-query", help="Search functions by keyword")
    p_query.add_argument("keyword", help="Search term (matched against labels, signatures, paths)")
    p_query.add_argument("--path", "-p", default=".", help="Repository root (default: .)")
    p_query.add_argument("--json", action="store_true", help="Output raw JSON")
    p_query.add_argument("--limit", "-n", type=int, default=20, help="Max results")

    # card-data
    p_card = sub.add_parser(
        "card-data",
        help="Extract enriched node data for a feature (JSON output, for card generation)",
    )
    p_card.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_card.add_argument("--feature", "-f", default=None,
                        help="Feature keyword — fuzzy-matches feature names and function labels")
    p_card.add_argument("--module", "-m", default=None,
                        help="Feature ID (from graph-list community_id) — exact match")
    p_card.add_argument("--limit", type=int, default=40, help="Max nodes in output")

    args = parser.parse_args()

    if args.command == "version":
        print(VERSION)
    elif args.command == "graph-root":
        cmd_graph_root(args)
    elif args.command == "graph-list":
        cmd_graph_list(args)
    elif args.command == "graph-query":
        cmd_graph_query(args)
    elif args.command == "card-data":
        cmd_card_data(args)


if __name__ == "__main__":
    main()
