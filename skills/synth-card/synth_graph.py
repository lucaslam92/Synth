#!/usr/bin/env python3
"""synth_graph.py — Synth Graph Tool for the /synth-card Claude Code skill.

这是一个独立脚本，无需安装 synth 包。
只有 graph-build 子命令需要外部依赖 graphifyy：

    pip install graphifyy

Usage:
    python3 synth_graph.py graph-build  [PATH] [--force]
    python3 synth_graph.py graph-list   [PATH] [--json]
    python3 synth_graph.py graph-query  KEYWORD [--path PATH] [--json] [--limit N]
    python3 synth_graph.py card-data    [PATH] [--feature TERM] [--module ID] [--limit N]
    python3 synth_graph.py version
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

VERSION = "0.3.0"


# ---------------------------------------------------------------------------
# graph-root  (replaces the inline Python block that was in SKILL.md)
# ---------------------------------------------------------------------------


def cmd_graph_root(args: argparse.Namespace) -> None:
    """Locate the repo root and probe the environment.  JSON → stdout."""
    start = Path(args.path).resolve()

    def find_repo_root(p: Path) -> Path:
        for candidate in [p, *p.parents]:
            if (candidate / ".git").exists():
                return candidate
        return p

    root = find_repo_root(start)
    graph_path = root / "graphify-out" / "graph.json"

    has_source = (
        any(root.rglob("*.py")) or
        any(root.rglob("*.ts")) or
        any(root.rglob("*.js")) or
        any(root.rglob("*.go")) or
        any(root.rglob("*.rs")) or
        any(root.rglob("*.java"))
    )

    graph_mtime: int | None = None
    if graph_path.exists():
        graph_mtime = int(graph_path.stat().st_mtime)

    print(json.dumps({
        "repo_root": str(root),
        "repo_name": root.name,
        "has_graph": graph_path.exists(),
        "graph_mtime": graph_mtime,
        "has_source": has_source,
    }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# graph-build
# ---------------------------------------------------------------------------


def cmd_graph_build(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()

    if not repo_root.exists():
        print(f"error: path not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    graph_path = repo_root / "graphify-out" / "graph.json"

    if graph_path.exists() and not args.force:
        print(f"✓ Graph already exists: {graph_path}", file=sys.stderr)
        print("  Pass --force to rebuild.", file=sys.stderr)
        return

    try:
        from graphify.extract import collect_files, extract
        from graphify.build import build
        from graphify.cluster import cluster
        from graphify.export import to_json
    except ImportError as exc:
        print(
            f"error: graphify not installed.\n"
            f"  Run: pip install graphifyy\n"
            f"  ({exc})",
            file=sys.stderr,
        )
        sys.exit(1)

    out_dir = repo_root / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"  building code graph for '{repo_root.name}' ({repo_root}) …", file=sys.stderr)

    code_files = collect_files(repo_root, root=repo_root)
    if not code_files:
        print(
            f"error: no supported code files found in {repo_root}\n"
            "Supported languages: Python, JS/TS, Go, Rust, Java, C/C++, Ruby, C#, Kotlin, Scala",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  found {len(code_files)} source file(s), extracting …", file=sys.stderr)

    ast_result = extract(code_files, cache_root=repo_root)
    nodes_found = len(ast_result.get("nodes", []))
    if nodes_found == 0:
        print(
            "error: AST extraction produced no nodes.\n"
            "The source files may not be in a supported language.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  extracted {nodes_found} node(s), building graph …", file=sys.stderr)

    G = build([ast_result], directed=True, root=repo_root)
    communities = cluster(G)
    graph_json_path = out_dir / "graph.json"
    to_json(G, communities, str(graph_json_path), force=True)

    data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    n_nodes = len(data.get("nodes", []))
    edges_key = "edges" if "edges" in data else "links"
    n_edges = len(data.get(edges_key, []))
    print(f"✓ Graph built: {graph_json_path}", file=sys.stderr)
    print(f"   {n_nodes} nodes · {n_edges} edges", file=sys.stderr)


# ---------------------------------------------------------------------------
# graph-list
# ---------------------------------------------------------------------------


def cmd_graph_list(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()
    graph_path = repo_root / "graphify-out" / "graph.json"

    if not graph_path.exists():
        print(
            f"error: no graph at {graph_path}\n"
            f"Run: python3 synth_graph.py graph-build {repo_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    modules = _extract_modules(data, repo_root)

    if args.json:
        print(json.dumps(modules, ensure_ascii=False, indent=2))
        return

    # Human-readable table
    print(f"\n{repo_root.name} — 检测到的模块\n")
    print(f"{'#':<4}  {'模块 (community_id)':<36}  {'节点数':>6}  {'主要路径':<28}  示例组件")
    print("-" * 110)
    for i, m in enumerate(modules, 1):
        sample = ", ".join(m["sample_nodes"][:3])
        main_file = m["files"][0] if m["files"] else "—"
        label = f"{m['label']}  ({m['community_id']})"
        print(f"{i:<4}  {label:<36}  {m['size']:>6}  {main_file:<28}  {sample}")
    print()


# ---------------------------------------------------------------------------
# graph-query
# ---------------------------------------------------------------------------


def cmd_graph_query(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()
    graph_path = repo_root / "graphify-out" / "graph.json"

    if not graph_path.exists():
        print(f"error: no graph at {graph_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    q = args.keyword.lower()

    matched = [
        n for n in data.get("nodes", [])
        if q in n.get("label", "").lower()
        or q in n.get("source_file", "").lower()
    ][:args.limit]

    if args.json:
        print(json.dumps(matched, ensure_ascii=False, indent=2))
        return

    if not matched:
        print(f"No nodes matched '{args.keyword}'")
        sys.exit(0)

    print(f"\n搜索结果: {args.keyword}\n")
    print(f"{'Label':<40}  {'Type':<14}  {'Source file':<40}  Module")
    print("-" * 110)
    for n in matched:
        print(
            f"{n.get('label', n['id']):<40}  "
            f"{n.get('file_type', ''):<14}  "
            f"{n.get('source_file', ''):<40}  "
            f"{n.get('community', '?')}"
        )
    print(f"\n共 {len(matched)} 个匹配节点（上限 {args.limit}）")


# ---------------------------------------------------------------------------
# card-data
# ---------------------------------------------------------------------------


def cmd_card_data(args: argparse.Namespace) -> None:
    repo_root = Path(args.path).resolve()
    graph_path = repo_root / "graphify-out" / "graph.json"

    if not graph_path.exists():
        print(
            f"error: no graph at {graph_path}\n"
            f"Run: python3 synth_graph.py graph-build {repo_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    edges_key = "edges" if "edges" in data else "links"

    feature: str | None = getattr(args, "feature", None)
    module: str | None = getattr(args, "module", None)
    limit_nodes: int = getattr(args, "limit", 40)

    # Case 1: no filter → return module list for caller to choose
    if feature is None and module is None:
        modules = _extract_modules(data, repo_root)
        print(json.dumps({
            "action": "choose_module",
            "repo": repo_root.name,
            "modules": modules,
        }, ensure_ascii=False, indent=2))
        return

    # Resolve target nodes
    if module is not None:
        target_nodes = [
            n for n in data.get("nodes", [])
            if str(n.get("community", "")) == str(module)
        ]
        scope_label = f"module {module}"
    else:
        assert feature is not None
        q = feature.lower()
        target_nodes = [
            n for n in data.get("nodes", [])
            if q in n.get("label", "").lower()
            or q in n.get("source_file", "").lower()
        ]
        scope_label = f"feature '{feature}'"

    if not target_nodes:
        print(json.dumps({
            "action": "no_match",
            "scope": scope_label,
            "modules": _extract_modules(data, repo_root),
        }, ensure_ascii=False, indent=2))
        return

    # Collect edges among matched nodes
    node_ids = {n["id"] for n in target_nodes}
    relevant_edges = [
        {
            "source": e.get("source"),
            "target": e.get("target"),
            "relation": e.get("relation", ""),
        }
        for e in data.get(edges_key, [])
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]

    # Infer a human label for this slice
    dirs = [
        str(Path(n.get("source_file", "")).parent)
        for n in target_nodes if n.get("source_file")
    ]
    slice_label = (
        Counter(dirs).most_common(1)[0][0].lstrip("./").replace("\\", "/")
        if dirs else scope_label
    )

    print(json.dumps({
        "action": "generate_card",
        "repo": repo_root.name,
        "label": slice_label,
        "scope": scope_label,
        "node_count": len(target_nodes),
        "nodes": [
            {
                "id": n["id"],
                "label": n.get("label", n["id"]),
                "file_type": n.get("file_type", ""),
                "source_file": n.get("source_file", ""),
            }
            for n in target_nodes[:limit_nodes]
        ],
        "edges": relevant_edges[:80],
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Shared helper — extract module summaries from graph.json data
# ---------------------------------------------------------------------------


def _extract_modules(data: dict, repo_root: Path) -> list[dict]:
    """Group nodes by community and return a sorted module summary list."""
    by_comm: dict[str, list[dict]] = {}
    for node in data.get("nodes", []):
        cid = str(node.get("community", "0"))
        by_comm.setdefault(cid, []).append(node)

    modules = []
    for cid, nodes in by_comm.items():
        dirs = [
            str(Path(n.get("source_file", "")).parent)
            for n in nodes if n.get("source_file")
        ]
        label = (
            Counter(dirs).most_common(1)[0][0].lstrip("./").replace("\\", "/")
            if dirs else f"module_{cid}"
        )
        if not label or label == ".":
            label = f"module_{cid}"
        modules.append({
            "community_id": cid,
            "label": label,
            "size": len(nodes),
            "files": sorted({
                str(Path(n.get("source_file", "")).parent.as_posix())
                for n in nodes if n.get("source_file")
            })[:5],
            "sample_nodes": [n.get("label", "") for n in nodes[:5]],
        })

    modules.sort(key=lambda m: -m["size"])
    return modules


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="synth_graph.py",
        description="Synth Graph Tool — helper for the /synth-card Claude Code skill",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # version
    sub.add_parser("version", help="Print version and exit")

    # graph-root
    p_root = sub.add_parser("graph-root", help="Locate repo root + check environment (JSON output)")
    p_root.add_argument("path", nargs="?", default=".", help="Starting path (default: .)")

    # graph-build
    p_build = sub.add_parser("graph-build", help="Build graphify-out/graph.json from source code")
    p_build.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_build.add_argument("--force", "-f", action="store_true", help="Rebuild even if graph.json exists")

    # graph-list
    p_list = sub.add_parser("graph-list", help="List detected modules in the code graph")
    p_list.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_list.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")

    # graph-query
    p_query = sub.add_parser("graph-query", help="Search nodes by keyword")
    p_query.add_argument("keyword", help="Search term (matched against node labels and file paths)")
    p_query.add_argument("--path", "-p", default=".", help="Repository root (default: .)")
    p_query.add_argument("--json", action="store_true", help="Output raw JSON")
    p_query.add_argument("--limit", "-n", type=int, default=20, help="Max nodes to return")

    # card-data
    p_card = sub.add_parser(
        "card-data",
        help="Extract graph data for a feature or module (JSON output, for card generation)",
    )
    p_card.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_card.add_argument("--feature", "-f", default=None,
                        help="Feature keyword — returns nodes matching this term")
    p_card.add_argument("--module", "-m", default=None,
                        help="Community ID (from graph-list) — returns the exact module")
    p_card.add_argument("--limit", type=int, default=40, help="Max nodes in output")

    args = parser.parse_args()

    if args.command == "version":
        print(VERSION)
    elif args.command == "graph-root":
        cmd_graph_root(args)
    elif args.command == "graph-build":
        cmd_graph_build(args)
    elif args.command == "graph-list":
        cmd_graph_list(args)
    elif args.command == "graph-query":
        cmd_graph_query(args)
    elif args.command == "card-data":
        cmd_card_data(args)


if __name__ == "__main__":
    main()
