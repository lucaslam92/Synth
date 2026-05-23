"""Graph merging and hierarchical community detection.

Pipeline:
  1. merge_graphs()       — combine all per-repo DiGraphs + cross-repo edges
                            into a single undirected Graph for community detection
  2. detect_communities() — Louvain (networkx built-in) or Leiden (graspologic)
  3. build_hierarchy()    — organise into repos → communities → nodes,
                            and identify cross-repo feature groups
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx

from .config import RepoConfig


# ---------------------------------------------------------------------------
# Data models (plain dicts — no ORM, no DB)
# ---------------------------------------------------------------------------

# CommunityData keys:
#   id            str   e.g. "user-service/community_3"
#   label         str   directory-inferred label (e.g. "auth")
#   repo          str
#   community_id  int
#   nodes         list[NodeSummary]  (label, file_type, source_file, line)
#   node_ids      list[str]  namespaced IDs
#   internal_edges list[EdgeSummary]
#   cross_repo_edges list[dict]
#   size          int

# FeatureGroup keys:
#   community_ids  list[str]
#   repos          list[str]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def merge_graphs(
    graphs: dict[str, nx.DiGraph],
    cross_edges: list[dict[str, Any]],
) -> nx.Graph:
    """Merge per-repo directed graphs + cross-repo edges into one undirected graph."""
    merged = nx.Graph()

    for _repo, g in graphs.items():
        for nid, data in g.nodes(data=True):
            merged.add_node(nid, **data)
        for src, tgt, data in g.edges(data=True):
            merged.add_edge(src, tgt, **data)

    # Cross-repo edges — only add if both endpoints already exist
    node_set = set(merged.nodes)
    for edge in cross_edges:
        src, tgt = edge["source"], edge["target"]
        if src in node_set and tgt in node_set:
            merged.add_edge(src, tgt, **{k: v for k, v in edge.items()
                                          if k not in ("source", "target")})

    return merged


def detect_communities(g: nx.Graph) -> dict[str, int]:
    """Return {node_id: community_id}.

    Uses Louvain from networkx (no extra deps).  Falls back to Leiden
    if graspologic is installed and provides better modularity.
    Falls back to connected components if networkx version is too old.
    """
    if len(g.nodes) == 0:
        return {}

    # --- Try Leiden (best quality, optional dep) ---
    try:
        from graspologic.partition import leiden  # type: ignore
        partition = leiden(nx.to_scipy_sparse_array(g))
        # graspologic returns dict {node_index: community_id}; map back to node IDs
        nodes = list(g.nodes)
        return {nodes[i]: cid for i, cid in partition.items()}
    except Exception:
        pass

    # --- Try Louvain (networkx >= 2.7) ---
    try:
        from networkx.algorithms.community import louvain_communities  # type: ignore
        communities = louvain_communities(g, seed=42)
        result: dict[str, int] = {}
        for cid, community in enumerate(communities):
            for node in community:
                result[node] = cid
        return result
    except Exception:
        pass

    # --- Fallback: connected components ---
    result = {}
    for cid, component in enumerate(nx.connected_components(g)):
        for node in component:
            result[node] = cid
    return result


def build_hierarchy(
    merged_graph: nx.Graph,
    node_to_community: dict[str, int],
    graphs: dict[str, nx.DiGraph],
) -> dict[str, Any]:
    """Build the three-level hierarchy: repos → communities → nodes.

    Returns:
        {
          "repos": {repo_name: {"name": str, "community_ids": list[str]}},
          "communities": {comm_id_str: CommunityData},
          "feature_groups": list[FeatureGroup],
        }
    """
    # --- group nodes by (repo, community_id) ---
    bucket: dict[tuple[str, int], list[str]] = {}
    for nid, cid in node_to_community.items():
        repo = merged_graph.nodes[nid].get("repo", "unknown")
        bucket.setdefault((repo, cid), []).append(nid)

    # Build reverse index: node_id → community key (for fast lookup)
    node_to_comm_key: dict[str, str] = {}

    communities: dict[str, dict[str, Any]] = {}
    for (repo, cid), node_ids in bucket.items():
        comm_key = f"{repo}/community_{cid}"

        # Node summaries (cap at 60 for token budget)
        node_summaries = []
        for nid in node_ids[:60]:
            d = merged_graph.nodes[nid]
            node_summaries.append({
                "id": nid,
                "label": d.get("label", ""),
                "file_type": d.get("file_type", ""),
                "source_file": d.get("source_file", ""),
                "line": d.get("line_number", 0),
                "snippet": d.get("snippet", ""),
            })

        # Internal edges (same community, not cross-repo, cap 80)
        internal_edges = []
        for src, tgt, edata in merged_graph.edges(data=True):
            if src not in node_ids or tgt not in node_ids:
                continue
            if edata.get("cross_repo", False):
                continue
            src_label = merged_graph.nodes[src].get("label", src.split("/")[-1])
            tgt_label = merged_graph.nodes[tgt].get("label", tgt.split("/")[-1])
            internal_edges.append({
                "source": src_label,
                "target": tgt_label,
                "relation": edata.get("relation", "related"),
            })
            if len(internal_edges) >= 80:
                break

        # Cross-repo edges touching this community (any endpoint)
        cross_repo_edges = []
        for src, tgt, edata in merged_graph.edges(data=True):
            if not edata.get("cross_repo", False):
                continue
            if src not in node_ids and tgt not in node_ids:
                continue
            cross_repo_edges.append({
                "source": src,
                "target": tgt,
                "relation": edata.get("relation", ""),
                "src_repo": edata.get("src_repo", ""),
                "tgt_repo": edata.get("tgt_repo", ""),
            })

        label = _infer_label(node_ids, merged_graph)

        communities[comm_key] = {
            "id": comm_key,
            "label": label,
            "repo": repo,
            "community_id": cid,
            "nodes": node_summaries,
            "node_ids": node_ids,
            "internal_edges": internal_edges,
            "cross_repo_edges": cross_repo_edges,
            "size": len(node_ids),
        }
        for nid in node_ids:
            node_to_comm_key[nid] = comm_key

    # --- repos ---
    repos: dict[str, dict[str, Any]] = {}
    for comm_key, comm in communities.items():
        repo = comm["repo"]
        if repo not in repos:
            repos[repo] = {"name": repo, "community_ids": []}
        repos[repo]["community_ids"].append(comm_key)

    # --- cross-repo feature groups ---
    feature_groups = _find_feature_groups(communities, node_to_comm_key, merged_graph)

    return {
        "repos": repos,
        "communities": communities,
        "feature_groups": feature_groups,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _infer_label(node_ids: list[str], g: nx.Graph) -> str:
    """Infer a readable module label from source file directory names."""
    dirs: list[str] = []
    for nid in node_ids:
        sf = g.nodes[nid].get("source_file", "")
        if not sf:
            continue
        parts = Path(sf).parts
        # Skip trivial top-level dirs
        for part in reversed(parts[:-1]):
            if part not in (".", "src", "lib", "app", "pkg", "internal", "main"):
                dirs.append(part)
                break
    if not dirs:
        # Fall back to most common node label prefix
        labels = [g.nodes[n].get("label", "") for n in node_ids if g.nodes[n].get("label")]
        if labels:
            # Strip camelCase to get a root word
            roots = [re.sub(r"([A-Z])", r" \1", lbl).split()[0].lower() for lbl in labels]
            return Counter(roots).most_common(1)[0][0]
        return "module"
    return Counter(dirs).most_common(1)[0][0]


def _find_feature_groups(
    communities: dict[str, dict],
    node_to_comm_key: dict[str, str],
    merged_graph: nx.Graph,
) -> list[dict[str, Any]]:
    """Find clusters of communities from different repos connected by cross-repo edges.

    Each connected component (in the community-level graph) that spans ≥ 2 repos
    is treated as a cross-repo feature group.
    """
    # Build a community-level graph
    comm_graph: nx.Graph = nx.Graph()
    comm_graph.add_nodes_from(communities.keys())

    for _, _, edata in merged_graph.edges(data=True):
        if not edata.get("cross_repo", False):
            continue
        src_comm = node_to_comm_key.get(edata.get("source", ""))  # may be missing
        tgt_comm = node_to_comm_key.get(edata.get("target", ""))

        # Also scan by endpoint lookup from the merged graph edge list
    # Re-do properly by iterating actual edge endpoints
    for src_nid, tgt_nid, edata in merged_graph.edges(data=True):
        if not edata.get("cross_repo", False):
            continue
        src_comm = node_to_comm_key.get(src_nid)
        tgt_comm = node_to_comm_key.get(tgt_nid)
        if src_comm and tgt_comm and src_comm != tgt_comm:
            src_repo = communities[src_comm]["repo"]
            tgt_repo = communities[tgt_comm]["repo"]
            if src_repo != tgt_repo:
                comm_graph.add_edge(src_comm, tgt_comm)

    feature_groups: list[dict[str, Any]] = []
    for component in nx.connected_components(comm_graph):
        repos_in_group = {communities[c]["repo"] for c in component if c in communities}
        if len(repos_in_group) >= 2:
            feature_groups.append({
                "community_ids": sorted(component),
                "repos": sorted(repos_in_group),
            })

    return feature_groups
