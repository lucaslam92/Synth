"""Shared fixtures and helpers for Synth test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import pytest

from synth.config import RepoConfig


# ---------------------------------------------------------------------------
# Graph JSON helpers
# ---------------------------------------------------------------------------

def make_graph_json(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a graphify-compatible graph.json dict."""
    return {"nodes": nodes, "edges": edges or []}


def write_graph_json(path: Path, data: dict[str, Any]) -> Path:
    """Write a graph.json and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Stock graph fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_nodes() -> list[dict]:
    return [
        {"id": "auth_controller", "label": "AuthController", "file_type": "class",
         "source_file": "src/auth/auth_controller.py", "line_number": 10},
        {"id": "auth_service",    "label": "AuthService",    "file_type": "class",
         "source_file": "src/auth/auth_service.py",    "line_number": 1},
        {"id": "token_util",      "label": "TokenUtil",      "file_type": "function",
         "source_file": "src/utils/token.py",           "line_number": 5},
    ]


@pytest.fixture
def simple_edges() -> list[dict]:
    return [
        {"source": "auth_controller", "target": "auth_service", "relation": "calls", "confidence": "HIGH"},
        {"source": "auth_service",    "target": "token_util",   "relation": "calls", "confidence": "HIGH"},
    ]


@pytest.fixture
def repo_a_dir(tmp_path: Path, simple_nodes: list, simple_edges: list) -> Path:
    """Write a minimal repo-a graph.json and return repo root."""
    repo_root = tmp_path / "repo-a"
    graph_path = repo_root / "graphify-out" / "graph.json"
    write_graph_json(graph_path, make_graph_json(simple_nodes, simple_edges))
    # write dummy source files so snippet reading doesn't fail silently
    for node in simple_nodes:
        src = repo_root / node["source_file"]
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f"# {node['label']}\npass\n" * 20, encoding="utf-8")
    return repo_root


@pytest.fixture
def repo_b_dir(tmp_path: Path) -> Path:
    """Write a minimal repo-b graph.json and return repo root."""
    nodes = [
        {"id": "order_service", "label": "OrderService", "file_type": "class",
         "source_file": "src/orders/service.py", "line_number": 1},
        {"id": "payment_gateway", "label": "PaymentGateway", "file_type": "class",
         "source_file": "src/payments/gateway.py", "line_number": 1},
    ]
    edges = [
        {"source": "order_service", "target": "payment_gateway",
         "relation": "calls", "confidence": "HIGH"},
    ]
    repo_root = tmp_path / "repo-b"
    write_graph_json(repo_root / "graphify-out" / "graph.json",
                     make_graph_json(nodes, edges))
    for node in nodes:
        src = repo_root / node["source_file"]
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f"# {node['label']}\npass\n" * 20, encoding="utf-8")
    return repo_root


@pytest.fixture
def repo_a_config(repo_a_dir: Path) -> RepoConfig:
    return RepoConfig(
        name="repo-a",
        graph=repo_a_dir / "graphify-out" / "graph.json",
        type="microservice",
        packages=["@co/repo-a"],
    )


@pytest.fixture
def repo_b_config(repo_b_dir: Path) -> RepoConfig:
    return RepoConfig(
        name="repo-b",
        graph=repo_b_dir / "graphify-out" / "graph.json",
        type="microservice",
        packages=["@co/repo-b"],
    )
