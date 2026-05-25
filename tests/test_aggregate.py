"""Tests for synth.aggregate — graph merge, community detection, hierarchy."""

from pathlib import Path

import networkx as nx
import pytest

from synth.aggregate import (
    _find_feature_groups,
    _infer_label,
    build_hierarchy,
    detect_communities,
    merge_graphs,
)
from synth.config import RepoConfig
from synth.ingest import load_all_graphs
from tests.conftest import make_graph_json, write_graph_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _simple_digraph(name: str, n: int = 3) -> nx.DiGraph:
    """Return a small DiGraph with namespaced node IDs."""
    g = nx.DiGraph()
    for i in range(n):
        nid = f"{name}/node_{i}"
        g.add_node(nid, repo=name, label=f"Node{i}",
                   source_file=f"src/{name}/file{i}.py", line_number=i + 1,
                   file_type="class", snippet="")
    for i in range(n - 1):
        g.add_edge(f"{name}/node_{i}", f"{name}/node_{i+1}",
                   relation="calls", cross_repo=False)
    return g


@pytest.fixture
def g_a() -> nx.DiGraph:
    return _simple_digraph("svc-a", n=4)


@pytest.fixture
def g_b() -> nx.DiGraph:
    return _simple_digraph("svc-b", n=3)


@pytest.fixture
def cross_edges(g_a: nx.DiGraph, g_b: nx.DiGraph) -> list[dict]:
    src = list(g_a.nodes)[0]
    tgt = list(g_b.nodes)[0]
    return [{
        "source": src, "target": tgt,
        "relation": "cross_repo_import",
        "confidence": "INFERRED",
        "cross_repo": True,
        "src_repo": "svc-a",
        "tgt_repo": "svc-b",
    }]


# ---------------------------------------------------------------------------
# merge_graphs
# ---------------------------------------------------------------------------


class TestMergeGraphs:
    def test_merged_contains_all_nodes(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        assert len(merged.nodes) == len(g_a.nodes) + len(g_b.nodes)

    def test_merged_contains_all_internal_edges(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        expected = len(g_a.edges) + len(g_b.edges)
        assert len(merged.edges) == expected

    def test_cross_edges_added(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph, cross_edges: list
    ) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, cross_edges)
        expected = len(g_a.edges) + len(g_b.edges) + len(cross_edges)
        assert len(merged.edges) == expected

    def test_cross_edges_with_missing_endpoints_skipped(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph
    ) -> None:
        bad_edge = {
            "source": "nonexistent/node", "target": "also/fake",
            "relation": "cross_repo_import", "cross_repo": True,
        }
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [bad_edge])
        # No bad edge added
        assert len(merged.edges) == len(g_a.edges) + len(g_b.edges)

    def test_returns_undirected_graph(self, g_a: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a}, [])
        assert isinstance(merged, nx.Graph)
        assert not isinstance(merged, nx.DiGraph)

    def test_empty_graphs_ok(self) -> None:
        merged = merge_graphs({}, [])
        assert len(merged.nodes) == 0


# ---------------------------------------------------------------------------
# detect_communities
# ---------------------------------------------------------------------------


class TestDetectCommunities:
    def test_returns_dict_node_to_int(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        result = detect_communities(merged)
        assert isinstance(result, dict)
        for k, v in result.items():
            assert isinstance(k, str)
            assert isinstance(v, int)

    def test_all_nodes_assigned(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        result = detect_communities(merged)
        assert set(result.keys()) == set(merged.nodes)

    def test_empty_graph_returns_empty(self) -> None:
        assert detect_communities(nx.Graph()) == {}

    def test_disconnected_repos_in_separate_communities(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph
    ) -> None:
        """Without cross-repo edges, svc-a and svc-b nodes should be in different communities."""
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        result = detect_communities(merged)
        a_communities = {result[n] for n in g_a.nodes}
        b_communities = {result[n] for n in g_b.nodes}
        # The two repos should not fully overlap in community assignment
        # (they are disconnected, so no community should span both entirely)
        assert a_communities.isdisjoint(b_communities)

    def test_single_node_graph(self) -> None:
        g = nx.Graph()
        g.add_node("repo-a/only", repo="repo-a")
        result = detect_communities(g)
        assert list(result.keys()) == ["repo-a/only"]


# ---------------------------------------------------------------------------
# build_hierarchy
# ---------------------------------------------------------------------------


class TestBuildHierarchy:
    def test_structure_keys(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a, "svc-b": g_b})
        assert set(h.keys()) == {"repos", "communities", "feature_groups"}

    def test_repos_keys_match_input(self, g_a: nx.DiGraph, g_b: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a, "svc-b": g_b})
        assert set(h["repos"].keys()) == {"svc-a", "svc-b"}

    def test_community_ids_referenced_in_repos(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph
    ) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a, "svc-b": g_b})
        all_comm_ids = set(h["communities"].keys())
        for repo_info in h["repos"].values():
            for cid in repo_info["community_ids"]:
                assert cid in all_comm_ids

    def test_community_data_fields_present(self, g_a: nx.DiGraph) -> None:
        merged = merge_graphs({"svc-a": g_a}, [])
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a})
        for comm in h["communities"].values():
            for field in ("id", "label", "repo", "nodes", "node_ids",
                          "internal_edges", "cross_repo_edges", "size"):
                assert field in comm, f"Missing field: {field}"

    def test_no_cross_repo_feature_groups_for_disconnected_repos(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph
    ) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, [])
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a, "svc-b": g_b})
        assert h["feature_groups"] == []

    def test_cross_repo_feature_group_created_when_connected(
        self, g_a: nx.DiGraph, g_b: nx.DiGraph, cross_edges: list
    ) -> None:
        merged = merge_graphs({"svc-a": g_a, "svc-b": g_b}, cross_edges)
        n2c = detect_communities(merged)
        h = build_hierarchy(merged, n2c, {"svc-a": g_a, "svc-b": g_b})
        assert len(h["feature_groups"]) >= 1
        for fg in h["feature_groups"]:
            assert len(fg["repos"]) >= 2


# ---------------------------------------------------------------------------
# _infer_label
# ---------------------------------------------------------------------------


class TestInferLabel:
    def _make_graph_with_sf(self, paths: list[str]) -> nx.Graph:
        g = nx.Graph()
        for i, sf in enumerate(paths):
            g.add_node(f"n{i}", source_file=sf)
        return g

    def test_infers_from_directory(self) -> None:
        g = self._make_graph_with_sf(["src/auth/controller.py"] * 3)
        label = _infer_label([f"n{i}" for i in range(3)], g)
        assert label == "auth"

    def test_most_common_directory_wins(self) -> None:
        g = self._make_graph_with_sf([
            "src/auth/a.py", "src/auth/b.py", "src/orders/c.py"
        ])
        label = _infer_label(["n0", "n1", "n2"], g)
        assert label == "auth"

    def test_fallback_to_label_prefix_when_no_source_file(self) -> None:
        g = nx.Graph()
        g.add_node("n0", source_file="", label="AuthController")
        g.add_node("n1", source_file="", label="AuthService")
        label = _infer_label(["n0", "n1"], g)
        assert label == "auth"

    def test_returns_module_when_nothing_useful(self) -> None:
        g = nx.Graph()
        g.add_node("n0", source_file="", label="")
        label = _infer_label(["n0"], g)
        assert label == "module"
