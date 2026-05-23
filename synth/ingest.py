"""Load graphify JSON graphs and namespace all node/edge IDs by repo name.

Expected input format (graphify graph.json):
  {
    "nodes": [{"id": str, "label": str, "file_type": str, "source_file": str, ...}],
    "edges": [{"source": str, "target": str, "relation": str, "confidence": str, ...}]
  }

After loading, every node ID becomes "{repo_name}/{original_id}" and every node
carries a "repo" attribute so downstream modules know which repo it belongs to.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from .config import RepoConfig

_SNIPPET_LINES = 10  # lines of source code to capture per node


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_repo_graph(repo: RepoConfig) -> nx.DiGraph:
    """Load and namespace a single repo's graphify graph.json."""
    path = repo.graph
    if not path.exists():
        raise FileNotFoundError(
            f"Graph not found for repo '{repo.name}': {path}\n"
            f"Run graphify inside that repository first:\n"
            f"  cd {path.parent.parent}  &&  graphify"
        )

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    g = nx.DiGraph()
    prefix = repo.name
    repo_root = repo.graph.parent.parent

    # --- nodes ---
    for node in data.get("nodes", []):
        nid = _ns(prefix, node["id"])
        attrs = {k: v for k, v in node.items() if k != "id"}
        attrs["original_id"] = node["id"]
        attrs["repo"] = repo.name
        attrs["snippet"] = _read_snippet(
            repo_root, node.get("source_file", ""), node.get("line_number", 0)
        )
        g.add_node(nid, **attrs)

    # --- edges ---
    node_set = set(g.nodes)
    for edge in data.get("edges", []):
        src = _ns(prefix, edge["source"])
        tgt = _ns(prefix, edge["target"])
        if src not in node_set or tgt not in node_set:
            # Skip dangling edges (can happen with partial graphs)
            continue
        attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
        attrs.setdefault("cross_repo", False)
        g.add_edge(src, tgt, **attrs)

    return g


def load_all_graphs(repos: list[RepoConfig]) -> dict[str, nx.DiGraph]:
    """Load graphs for all configured repos. Raises on first missing graph."""
    return {repo.name: load_repo_graph(repo) for repo in repos}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ns(prefix: str, node_id: str) -> str:
    """Namespace a node ID: 'user-service/auth_controller'."""
    return f"{prefix}/{node_id}"


def _read_snippet(repo_root: Path, source_file: str, line_number: int) -> str:
    """Read up to _SNIPPET_LINES lines of source starting at line_number."""
    if not source_file or line_number <= 0:
        return ""
    path = repo_root / source_file
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line_number - 1)
        return "\n".join(lines[start : start + _SNIPPET_LINES])
    except OSError:
        return ""
