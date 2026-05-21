"""Cross-repo edge detection.

Three strategies, applied in order of reliability:

1. Import-based  (HIGH confidence)
   A node in Repo A has an outgoing `imports` edge whose target label matches
   a declared package name of Repo B.  Creates a `cross_repo_import` edge from
   the *importing file node* in A to the *highest-degree node* in B (its de-facto
   public interface).

2. HTTP route matching  (MEDIUM confidence)
   A node in Repo A whose label looks like a URL path (e.g. "/api/users") matches
   a route-definition node in Repo B with the same path pattern.

3. Symbol name matching  (LOW / AMBIGUOUS confidence)
   A PascalCase class or interface name appears as a node in two or more repos.
   This catches interface/implementation pairs common in microservice stubs.
   Filtered aggressively: min length 8, must start with uppercase, skips common
   generic names.  Only enabled for `library` and `monorepo` repo types.
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx

from .config import RepoConfig

# Names too generic to link on (common across every codebase)
_GENERIC_LABELS = frozenset({
    "index", "main", "app", "server", "client", "config", "utils", "helpers",
    "types", "constants", "base", "common", "shared", "service", "controller",
    "repository", "handler", "middleware", "model", "entity", "interface",
    "manager", "factory", "provider", "module", "component", "router",
})

_URL_PATH_RE = re.compile(r"^/[a-zA-Z0-9/_\-{}:]+$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_cross_repo_edges(
    graphs: dict[str, nx.DiGraph],
    repos: list[RepoConfig],
) -> list[dict[str, Any]]:
    """Return a list of cross-repo edge dicts to be added to the merged graph."""
    cross_edges: list[dict[str, Any]] = []

    # Build lookup structures
    pkg_to_repo = _build_pkg_map(repos)
    repo_interface_node = {
        name: _find_interface_node(g, name) for name, g in graphs.items()
    }
    # label → list of (repo_name, node_id) — for symbol matching
    label_index: dict[str, list[tuple[str, str]]] = {}
    for repo_name, g in graphs.items():
        for nid, data in g.nodes(data=True):
            lbl = data.get("label", "").strip()
            if lbl:
                label_index.setdefault(lbl, []).append((repo_name, nid))

    for src_repo_name, g in graphs.items():
        # ------------------------------------------------------------------
        # Strategy 1: import-based
        # ------------------------------------------------------------------
        for nid, ndata in g.nodes(data=True):
            for _, tgt_id, edata in g.out_edges(nid, data=True):
                if edata.get("relation") != "imports":
                    continue
                imported_label = g.nodes[tgt_id].get("label", "")
                matched_repo = _match_package(imported_label, pkg_to_repo)
                if matched_repo and matched_repo != src_repo_name:
                    iface_node = repo_interface_node[matched_repo]
                    cross_edges.append({
                        "source": nid,
                        "target": iface_node,
                        "relation": "cross_repo_import",
                        "confidence": "INFERRED",
                        "cross_repo": True,
                        "src_repo": src_repo_name,
                        "tgt_repo": matched_repo,
                    })

        # ------------------------------------------------------------------
        # Strategy 2: HTTP route matching
        # ------------------------------------------------------------------
        src_routes = _collect_routes(g)
        for tgt_repo_name, tgt_g in graphs.items():
            if tgt_repo_name == src_repo_name:
                continue
            tgt_routes = _collect_routes(tgt_g)
            for path, caller_nid in src_routes.items():
                if path in tgt_routes:
                    cross_edges.append({
                        "source": caller_nid,
                        "target": tgt_routes[path],
                        "relation": "cross_repo_http_call",
                        "confidence": "INFERRED",
                        "cross_repo": True,
                        "src_repo": src_repo_name,
                        "tgt_repo": tgt_repo_name,
                        "route": path,
                    })

    # ------------------------------------------------------------------
    # Strategy 3: symbol name matching (library / monorepo pairs only)
    # ------------------------------------------------------------------
    library_repos = {r.name for r in repos if r.type in ("library", "monorepo")}
    for label, occurrences in label_index.items():
        if not _is_linkable_symbol(label):
            continue
        repo_names = {repo for repo, _ in occurrences}
        # Only link when at least one side is a library/monorepo
        if not (repo_names & library_repos):
            continue
        if len(repo_names) < 2:
            continue
        # Create edges between the first occurrence per repo (de-dup)
        per_repo: dict[str, str] = {}
        for repo_name, nid in occurrences:
            per_repo.setdefault(repo_name, nid)
        items = list(per_repo.items())
        for i, (repo_a, nid_a) in enumerate(items):
            for repo_b, nid_b in items[i + 1:]:
                cross_edges.append({
                    "source": nid_a,
                    "target": nid_b,
                    "relation": "cross_repo_same_symbol",
                    "confidence": "AMBIGUOUS",
                    "cross_repo": True,
                    "src_repo": repo_a,
                    "tgt_repo": repo_b,
                })

    return _deduplicate(cross_edges)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_pkg_map(repos: list[RepoConfig]) -> dict[str, str]:
    """Map normalised package names → repo name."""
    m: dict[str, str] = {}
    for repo in repos:
        for pkg in repo.packages:
            m[_normalise_pkg(pkg)] = repo.name
        # Also map the repo name itself as a fallback
        m[_normalise_pkg(repo.name)] = repo.name
    return m


def _normalise_pkg(pkg: str) -> str:
    """Normalise a package name for fuzzy matching."""
    return pkg.lower().lstrip("@").replace("-", "_").replace("/", "_").replace(".", "_")


def _match_package(label: str, pkg_to_repo: dict[str, str]) -> str | None:
    """Return the repo name if the label matches a known package, else None."""
    norm = _normalise_pkg(label)
    if norm in pkg_to_repo:
        return pkg_to_repo[norm]
    # Prefix match: "shared_utils_v2" → "shared_utils"
    for pkg, repo in pkg_to_repo.items():
        if norm.startswith(pkg) or pkg.startswith(norm):
            return repo
    return None


def _find_interface_node(g: nx.DiGraph, repo_name: str) -> str:
    """Find the best representative 'public interface' node for a repo.

    Heuristic: node with the highest out-degree (exports most things).
    Falls back to a synthetic root placeholder.
    """
    if not g.nodes:
        return f"{repo_name}/__root__"
    return max(g.nodes, key=lambda n: g.out_degree(n))


def _collect_routes(g: nx.DiGraph) -> dict[str, str]:
    """Return {url_path: node_id} for nodes whose label looks like a URL path."""
    routes: dict[str, str] = {}
    for nid, data in g.nodes(data=True):
        label = data.get("label", "")
        if _URL_PATH_RE.match(label):
            routes[label] = nid
    return routes


def _is_linkable_symbol(label: str) -> bool:
    """True if this symbol name is specific enough to be cross-linked."""
    if len(label) < 8:
        return False
    if label.lower() in _GENERIC_LABELS:
        return False
    # Must start with uppercase (PascalCase class / interface names)
    if not label[0].isupper():
        return False
    return True


def _deduplicate(edges: list[dict]) -> list[dict]:
    """Remove duplicate cross-repo edges (same src/tgt/relation)."""
    seen: set[tuple] = set()
    result = []
    for e in edges:
        key = (e["source"], e["target"], e["relation"])
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result
