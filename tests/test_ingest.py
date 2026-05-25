"""Tests for synth.ingest — graph loading and namespacing."""

from pathlib import Path

import networkx as nx
import pytest

from synth.config import RepoConfig
from synth.ingest import load_all_graphs, load_repo_graph
from tests.conftest import make_graph_json, write_graph_json


class TestLoadRepoGraph:
    def test_loads_nodes(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        assert len(g.nodes) == 3

    def test_nodes_are_namespaced(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        for nid in g.nodes:
            assert nid.startswith("repo-a/"), f"Node {nid!r} not namespaced"

    def test_repo_attribute_set_on_nodes(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        for nid, data in g.nodes(data=True):
            assert data.get("repo") == "repo-a"

    def test_original_id_preserved(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        original_ids = {data["original_id"] for _, data in g.nodes(data=True)}
        assert "auth_controller" in original_ids

    def test_loads_edges(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        assert len(g.edges) == 2

    def test_edges_are_namespaced(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        for src, tgt in g.edges():
            assert src.startswith("repo-a/")
            assert tgt.startswith("repo-a/")

    def test_returns_digraph(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        assert isinstance(g, nx.DiGraph)

    def test_missing_graph_raises(self, tmp_path: Path) -> None:
        cfg = RepoConfig(
            name="missing",
            graph=tmp_path / "no_such" / "graph.json",
        )
        with pytest.raises(FileNotFoundError, match="missing"):
            load_repo_graph(cfg)

    def test_snippet_populated_for_existing_source(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        # At least one node should have a non-empty snippet
        snippets = [data.get("snippet", "") for _, data in g.nodes(data=True)]
        assert any(s for s in snippets), "Expected at least one snippet to be non-empty"

    def test_snippet_empty_for_missing_source(self, tmp_path: Path) -> None:
        """Nodes whose source_file doesn't exist should have empty snippet, not crash."""
        nodes = [{"id": "foo", "label": "Foo", "file_type": "class",
                  "source_file": "src/nonexistent.py", "line_number": 1}]
        graph_path = tmp_path / "repo-x" / "graphify-out" / "graph.json"
        write_graph_json(graph_path, make_graph_json(nodes))
        cfg = RepoConfig(name="repo-x", graph=graph_path)
        g = load_repo_graph(cfg)
        assert g.nodes["repo-x/foo"]["snippet"] == ""

    def test_dangling_edges_skipped(self, tmp_path: Path) -> None:
        """Edges whose endpoints don't exist in nodes should be silently dropped."""
        nodes = [{"id": "a", "label": "A", "file_type": "class",
                  "source_file": "", "line_number": 0}]
        edges = [{"source": "a", "target": "NONEXISTENT", "relation": "calls"}]
        graph_path = tmp_path / "repo-d" / "graphify-out" / "graph.json"
        write_graph_json(graph_path, make_graph_json(nodes, edges))
        cfg = RepoConfig(name="repo-d", graph=graph_path)
        g = load_repo_graph(cfg)
        assert len(g.edges) == 0

    def test_cross_repo_attribute_defaults_false(self, repo_a_config: RepoConfig) -> None:
        g = load_repo_graph(repo_a_config)
        for _, _, data in g.edges(data=True):
            assert data.get("cross_repo") is False


class TestLoadAllGraphs:
    def test_returns_dict_keyed_by_repo_name(
        self, repo_a_config: RepoConfig, repo_b_config: RepoConfig
    ) -> None:
        graphs = load_all_graphs([repo_a_config, repo_b_config])
        assert set(graphs.keys()) == {"repo-a", "repo-b"}

    def test_each_value_is_digraph(
        self, repo_a_config: RepoConfig, repo_b_config: RepoConfig
    ) -> None:
        for g in load_all_graphs([repo_a_config, repo_b_config]).values():
            assert isinstance(g, nx.DiGraph)

    def test_raises_on_first_missing_graph(
        self, repo_a_config: RepoConfig, tmp_path: Path
    ) -> None:
        missing = RepoConfig(name="ghost", graph=tmp_path / "ghost" / "graph.json")
        with pytest.raises(FileNotFoundError):
            load_all_graphs([repo_a_config, missing])
