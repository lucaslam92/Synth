"""Tests for synth.config — TOML config loading."""

from pathlib import Path

import pytest

from synth.config import CacheConfig, LLMConfig, OutputConfig, RepoConfig, SynthConfig, load_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "synth.toml"
    p.write_text(content, encoding="utf-8")
    return p


MINIMAL_TOML = """\
[[repos]]
name  = "svc-a"
graph = "svc-a/graphify-out/graph.json"
"""

FULL_TOML = """\
[output]
language = "en"
format   = "json"
dir      = "out"

[cache]
dir     = ".cache"
enabled = false

[llm]
model      = "claude-haiku-4-5-20251001"
max_tokens = 1024

[[repos]]
name     = "svc-a"
graph    = "svc-a/graph.json"
type     = "microservice"
packages = ["@co/svc-a"]

[[repos]]
name     = "shared"
graph    = "shared/graph.json"
type     = "library"
packages = ["@co/shared", "shared_lib"]
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_minimal_config_loads(self, tmp_path: Path) -> None:
        cfg = load_config(_write_toml(tmp_path, MINIMAL_TOML))
        assert len(cfg.repos) == 1
        assert cfg.repos[0].name == "svc-a"

    def test_full_config_parses_correctly(self, tmp_path: Path) -> None:
        cfg = load_config(_write_toml(tmp_path, FULL_TOML))

        # output
        assert cfg.output.language == "en"
        assert cfg.output.format == "json"
        assert cfg.output.dir == Path("out")

        # cache
        assert cfg.cache.dir == Path(".cache")
        assert cfg.cache.enabled is False

        # llm
        assert cfg.llm.model == "claude-haiku-4-5-20251001"
        assert cfg.llm.max_tokens == 1024

        # repos
        assert len(cfg.repos) == 2
        svc_a, shared = cfg.repos
        assert svc_a.name == "svc-a"
        assert svc_a.type == "microservice"
        assert svc_a.packages == ["@co/svc-a"]
        assert shared.type == "library"
        assert "@co/shared" in shared.packages

    def test_defaults_applied_when_sections_omitted(self, tmp_path: Path) -> None:
        cfg = load_config(_write_toml(tmp_path, MINIMAL_TOML))
        assert cfg.output.language == "zh"
        assert cfg.output.format == "markdown"
        assert cfg.cache.enabled is True
        assert cfg.llm.model == "claude-opus-4-6"
        assert cfg.llm.max_tokens == 2048
        assert cfg.repos[0].type == "microservice"
        assert cfg.repos[0].packages == []

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="synth init"):
            load_config(tmp_path / "nonexistent.toml")

    def test_missing_name_field_raises(self, tmp_path: Path) -> None:
        bad = """\
[[repos]]
graph = "somewhere/graph.json"
"""
        with pytest.raises(ValueError, match="name"):
            load_config(_write_toml(tmp_path, bad))

    def test_missing_graph_field_raises(self, tmp_path: Path) -> None:
        bad = """\
[[repos]]
name = "svc"
"""
        with pytest.raises(ValueError, match="graph"):
            load_config(_write_toml(tmp_path, bad))

    def test_empty_repos_raises(self, tmp_path: Path) -> None:
        empty = "[output]\nlanguage = 'zh'\n"
        with pytest.raises(ValueError, match="repos"):
            load_config(_write_toml(tmp_path, empty))

    def test_multiple_repos_loaded_in_order(self, tmp_path: Path) -> None:
        cfg = load_config(_write_toml(tmp_path, FULL_TOML))
        names = [r.name for r in cfg.repos]
        assert names == ["svc-a", "shared"]

    def test_graph_path_is_pathlib_path(self, tmp_path: Path) -> None:
        cfg = load_config(_write_toml(tmp_path, MINIMAL_TOML))
        assert isinstance(cfg.repos[0].graph, Path)
