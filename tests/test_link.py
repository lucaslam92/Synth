"""Tests for synth.link — cross-repo edge detection."""

from pathlib import Path

import networkx as nx
import pytest

from synth.config import RepoConfig
from synth.ingest import load_all_graphs
from synth.link import (
    _is_linkable_symbol,
    _match_package,
    _normalise_pkg,
    find_cross_repo_edges,
)
from tests.conftest import make_graph_json, write_graph_json


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestNormalisePkg:
    def test_lowercase(self) -> None:
        assert _normalise_pkg("MyPkg") == "mypkg"

    def test_strip_at_prefix(self) -> None:
        assert _normalise_pkg("@company/my-pkg") == "company_my_pkg"

    def test_replace_hyphens(self) -> None:
        assert _normalise_pkg("my-service-a") == "my_service_a"

    def test_replace_dots(self) -> None:
        assert _normalise_pkg("com.example.lib") == "com_example_lib"


class TestMatchPackage:
    def test_exact_match(self) -> None:
        pkg_map = {"co_svc_a": "svc-a"}
        assert _match_package("@co/svc-a", pkg_map) == "svc-a"

    def test_no_match_returns_none(self) -> None:
        assert _match_package("unknown", {"co_svc_a": "svc-a"}) is None

    def test_prefix_match(self) -> None:
        pkg_map = {"co_shared": "shared"}
        # "co_shared_v2" starts with "co_shared"
        assert _match_package("@co/shared-v2", pkg_map) == "shared"


class TestIsLinkableSymbol:
    def test_short_label_rejected(self) -> None:
        assert not _is_linkable_symbol("Foo")   # len < 8

    def test_lowercase_rejected(self) -> None:
        assert not _is_linkable_symbol("authService")

    def test_generic_name_rejected(self) -> None:
        assert not _is_linkable_symbol("Controller")  # in _GENERIC_LABELS? No...
        # "controller" is in _GENERIC_LABELS (lowercase check)
        assert not _is_linkable_symbol("Interface")

    def test_valid_symbol_accepted(self) -> None:
        assert _is_linkable_symbol("PaymentGateway")
        assert _is_linkable_symbol("UserRepository")

    def test_exact_8_chars_accepted(self) -> None:
        # Exactly 8 chars, starts upper
        assert _is_linkable_symbol("AuthRepo")  # len=8


# ---------------------------------------------------------------------------
# Integration tests: find_cross_repo_edges
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, name: str, nodes: list, edges: list, packages: list,
               repo_type: str = "microservice") -> tuple[RepoConfig, nx.DiGraph]:
    """Write graph.json and load it, returning (config, graph)."""
    graph_path = tmp_path / name / "graphify-out" / "graph.json"
    write_graph_json(graph_path, make_graph_json(nodes, edges))
    cfg = RepoConfig(name=name, graph=graph_path, type=repo_type, packages=packages)
    graphs = load_all_graphs([cfg])
    return cfg, graphs[name]


class TestFindCrossRepoEdges:
    def test_no_cross_edges_when_no_imports(self, tmp_path: Path) -> None:
        nodes_a = [{"id": "svc", "label": "SvcA", "file_type": "class",
                    "source_file": "", "line_number": 0}]
        nodes_b = [{"id": "svc", "label": "SvcB", "file_type": "class",
                    "source_file": "", "line_number": 0}]
        cfg_a, g_a = _make_repo(tmp_path, "repo-a", nodes_a, [], ["@co/repo-a"])
        cfg_b, g_b = _make_repo(tmp_path, "repo-b", nodes_b, [], ["@co/repo-b"])
        edges = find_cross_repo_edges({"repo-a": g_a, "repo-b": g_b}, [cfg_a, cfg_b])
        assert edges == []

    def test_import_based_cross_edge_detected(self, tmp_path: Path) -> None:
        """Repo-a imports @co/repo-b → expect a cross_repo_import edge."""
        nodes_a = [
            {"id": "caller", "label": "Caller", "file_type": "class",
             "source_file": "", "line_number": 0},
            {"id": "pkg_b",  "label": "@co/repo-b", "file_type": "package",
             "source_file": "", "line_number": 0},
        ]
        edges_a = [{"source": "caller", "target": "pkg_b", "relation": "imports"}]
        nodes_b = [
            {"id": "handler", "label": "Handler", "file_type": "class",
             "source_file": "", "line_number": 0},
        ]
        cfg_a, g_a = _make_repo(tmp_path, "repo-a", nodes_a, edges_a, ["@co/repo-a"])
        cfg_b, g_b = _make_repo(tmp_path, "repo-b", nodes_b, [],       ["@co/repo-b"])
        edges = find_cross_repo_edges({"repo-a": g_a, "repo-b": g_b}, [cfg_a, cfg_b])
        cross = [e for e in edges if e["relation"] == "cross_repo_import"]
        assert len(cross) >= 1
        assert cross[0]["src_repo"] == "repo-a"
        assert cross[0]["tgt_repo"] == "repo-b"
        assert cross[0]["cross_repo"] is True

    def test_http_route_cross_edge_detected(self, tmp_path: Path) -> None:
        """Repo-a has route /api/orders and repo-b also has route /api/orders."""
        nodes_a = [{"id": "route_a", "label": "/api/orders",
                    "file_type": "route", "source_file": "", "line_number": 0}]
        nodes_b = [{"id": "route_b", "label": "/api/orders",
                    "file_type": "route", "source_file": "", "line_number": 0}]
        cfg_a, g_a = _make_repo(tmp_path, "repo-a", nodes_a, [], [])
        cfg_b, g_b = _make_repo(tmp_path, "repo-b", nodes_b, [], [])
        edges = find_cross_repo_edges({"repo-a": g_a, "repo-b": g_b}, [cfg_a, cfg_b])
        http_edges = [e for e in edges if e["relation"] == "cross_repo_http_call"]
        assert len(http_edges) >= 1

    def test_symbol_matching_for_library(self, tmp_path: Path) -> None:
        """PascalCase symbol in both svc (microservice) and lib (library) creates an edge."""
        nodes_svc = [{"id": "pg",  "label": "PaymentGateway",
                      "file_type": "class", "source_file": "", "line_number": 0}]
        nodes_lib = [{"id": "pg",  "label": "PaymentGateway",
                      "file_type": "interface", "source_file": "", "line_number": 0}]
        cfg_svc, g_svc = _make_repo(tmp_path, "svc",     nodes_svc, [], [],     "microservice")
        cfg_lib, g_lib = _make_repo(tmp_path, "shared",  nodes_lib, [], [],     "library")
        edges = find_cross_repo_edges(
            {"svc": g_svc, "shared": g_lib}, [cfg_svc, cfg_lib]
        )
        sym_edges = [e for e in edges if e["relation"] == "cross_repo_same_symbol"]
        assert len(sym_edges) >= 1

    def test_deduplication_removes_duplicates(self, tmp_path: Path) -> None:
        """Same import matched multiple times should not produce duplicate edges."""
        nodes_a = [
            {"id": "caller1", "label": "Caller1", "file_type": "class",
             "source_file": "", "line_number": 0},
            {"id": "caller2", "label": "Caller2", "file_type": "class",
             "source_file": "", "line_number": 0},
            {"id": "pkg_b",   "label": "@co/repo-b", "file_type": "package",
             "source_file": "", "line_number": 0},
        ]
        edges_a = [
            {"source": "caller1", "target": "pkg_b", "relation": "imports"},
            {"source": "caller2", "target": "pkg_b", "relation": "imports"},
        ]
        nodes_b = [{"id": "h", "label": "Handler", "file_type": "class",
                    "source_file": "", "line_number": 0}]
        cfg_a, g_a = _make_repo(tmp_path, "repo-a", nodes_a, edges_a, [])
        cfg_b, g_b = _make_repo(tmp_path, "repo-b", nodes_b, [],       ["@co/repo-b"])
        edges = find_cross_repo_edges({"repo-a": g_a, "repo-b": g_b}, [cfg_a, cfg_b])
        # There should be at most 2 import edges (one per caller), not more
        import_edges = [e for e in edges if e["relation"] == "cross_repo_import"]
        keys = [(e["source"], e["target"], e["relation"]) for e in import_edges]
        assert len(keys) == len(set(keys)), "Duplicate edges found"

    def test_same_repo_not_cross_linked(self, tmp_path: Path) -> None:
        """Symbol matching should never link a repo to itself."""
        nodes = [{"id": "pg", "label": "PaymentGateway",
                  "file_type": "class", "source_file": "", "line_number": 0}]
        cfg, g = _make_repo(tmp_path, "svc", nodes, [], [], "library")
        edges = find_cross_repo_edges({"svc": g}, [cfg])
        assert edges == []
