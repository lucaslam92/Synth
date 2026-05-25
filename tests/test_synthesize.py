"""Tests for synth.synthesize — LLM synthesis (API mocked)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from synth.cache import Cache
from synth.config import LLMConfig
from synth.synthesize import (
    Synthesizer,
    _build_code_map,
    _format_cross_edges,
    _format_edges,
    _format_nodes,
    _module_cache_key,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_cfg() -> LLMConfig:
    return LLMConfig(model="claude-haiku-4-5-20251001", max_tokens=512, api_key="sk-test-fake")


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / ".synth-cache")


@pytest.fixture
def synth(llm_cfg: LLMConfig, cache: Cache) -> Synthesizer:
    """Synthesizer with a mocked Anthropic client.

    anthropic is now lazily imported via _import_anthropic(), so we patch
    the class directly on the already-imported module.
    """
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="**模块名称**：认证模块\n**职责概述**：处理用户认证。\n- AuthController 接收请求")]
    mock_msg.usage.input_tokens = 100
    mock_msg.usage.output_tokens = 50

    with patch("anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_msg
        s = Synthesizer(llm_cfg, cache, language="zh")
    # keep the mock client alive after the context exits
    s._client = MockClient.return_value
    return s


@pytest.fixture
def simple_community() -> dict:
    return {
        "id": "repo-a/community_0",
        "label": "auth",
        "repo": "repo-a",
        "community_id": 0,
        "nodes": [
            {"id": "repo-a/auth_controller", "label": "AuthController",
             "file_type": "class", "source_file": "src/auth/controller.py", "line": 10,
             "snippet": "class AuthController:\n    pass"},
            {"id": "repo-a/auth_service", "label": "AuthService",
             "file_type": "class", "source_file": "src/auth/service.py", "line": 1,
             "snippet": "class AuthService:\n    pass"},
        ],
        "internal_edges": [
            {"source": "AuthController", "target": "AuthService", "relation": "calls"},
        ],
        "cross_repo_edges": [],
        "size": 2,
    }


# ---------------------------------------------------------------------------
# Unit tests: formatting helpers
# ---------------------------------------------------------------------------


class TestFormatNodes:
    def test_basic_output(self) -> None:
        nodes = [{"label": "MyClass", "file_type": "class",
                  "source_file": "src/my.py", "line": 5, "snippet": ""}]
        result = _format_nodes(nodes)
        assert "`MyClass`" in result
        assert "src/my.py:5" in result

    def test_empty_nodes(self) -> None:
        result = _format_nodes([])
        assert "无实体信息" in result or "(no entity info)" in result.lower() or result

    def test_no_source_file_no_location(self) -> None:
        nodes = [{"label": "Foo", "file_type": "fn",
                  "source_file": "", "line": 0, "snippet": ""}]
        result = _format_nodes(nodes)
        assert ":" not in result or "Foo" in result


class TestFormatEdges:
    def test_basic_output(self) -> None:
        edges = [{"source": "A", "target": "B", "relation": "calls"}]
        result = _format_edges(edges)
        assert "A" in result and "B" in result and "calls" in result

    def test_deduplication(self) -> None:
        edges = [
            {"source": "A", "target": "B", "relation": "calls"},
            {"source": "A", "target": "B", "relation": "calls"},
        ]
        result = _format_edges(edges)
        assert result.count("A →") == 1

    def test_empty_edges(self) -> None:
        result = _format_edges([])
        assert result == ""


class TestFormatCrossEdges:
    def test_no_edges(self) -> None:
        result = _format_cross_edges([], "zh")
        assert "无跨服务" in result

    def test_no_edges_en(self) -> None:
        result = _format_cross_edges([], "en")
        assert "no cross-service" in result.lower()

    def test_edge_formatted(self) -> None:
        edges = [{"src_repo": "svc-a", "tgt_repo": "svc-b", "relation": "cross_repo_import"}]
        result = _format_cross_edges(edges, "zh")
        assert "svc-a" in result and "svc-b" in result

    def test_deduplication(self) -> None:
        edges = [
            {"src_repo": "a", "tgt_repo": "b", "relation": "import"},
            {"src_repo": "a", "tgt_repo": "b", "relation": "import"},
        ]
        result = _format_cross_edges(edges, "zh")
        assert result.count("[a]") == 1


class TestModuleCacheKey:
    def test_same_community_same_key(self, simple_community: dict) -> None:
        k1 = _module_cache_key(simple_community)
        k2 = _module_cache_key(simple_community)
        import json
        assert json.dumps(k1, sort_keys=True) == json.dumps(k2, sort_keys=True)

    def test_different_nodes_different_key(self, simple_community: dict) -> None:
        import copy, json
        c2 = copy.deepcopy(simple_community)
        c2["nodes"][0]["label"] = "ChangedClass"
        k1 = _module_cache_key(simple_community)
        k2 = _module_cache_key(c2)
        assert json.dumps(k1, sort_keys=True) != json.dumps(k2, sort_keys=True)


# ---------------------------------------------------------------------------
# Unit tests: _build_code_map
# ---------------------------------------------------------------------------


class TestBuildCodeMap:
    def test_finds_entity_in_bullet(self) -> None:
        text = "**核心功能点**：\n- AuthController 处理认证请求\n- 其他功能"
        nodes = [{"id": "repo/AuthController", "label": "AuthController",
                  "source_file": "src/auth.py", "line": 1, "snippet": "pass"}]
        code_map = _build_code_map(text, nodes)
        # At least one entry should reference AuthController
        all_refs = [ref for refs in code_map.values() for ref in refs]
        node_ids = [r["node_id"] for r in all_refs]
        assert "repo/AuthController" in node_ids

    def test_empty_text_returns_empty_map(self) -> None:
        nodes = [{"id": "n", "label": "SomeClass", "source_file": "x.py",
                  "line": 1, "snippet": ""}]
        assert _build_code_map("", nodes) == {}

    def test_nodes_without_source_excluded(self) -> None:
        text = "- FooClass does something"
        nodes = [{"id": "n", "label": "FooClass", "source_file": "", "line": 0,
                  "snippet": ""}]
        code_map = _build_code_map(text, nodes)
        assert code_map == {}

    def test_short_labels_excluded(self) -> None:
        """Labels shorter than _MIN_LABEL_LEN (4) shouldn't be indexed."""
        text = "- Foo does something"
        nodes = [{"id": "n", "label": "Foo", "source_file": "x.py", "line": 1,
                  "snippet": ""}]
        code_map = _build_code_map(text, nodes)
        assert code_map == {}

    def test_backtick_entity_extracted(self) -> None:
        text = "关键实体 `AuthService` 负责验证"
        nodes = [{"id": "n", "label": "AuthService", "source_file": "src/auth.py",
                  "line": 5, "snippet": "class AuthService: pass"}]
        code_map = _build_code_map(text, nodes)
        assert "AuthService" in code_map
        assert code_map["AuthService"][0]["file"] == "src/auth.py"


# ---------------------------------------------------------------------------
# Integration tests: Synthesizer (mocked API)
# ---------------------------------------------------------------------------


class TestSynthesizerModuleLevel:
    def test_synthesize_module_returns_dict(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        result = synth.synthesize_module(simple_community)
        assert isinstance(result, dict)
        assert "text" in result
        assert "code_map" in result

    def test_synthesize_module_calls_llm(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        synth.synthesize_module(simple_community)
        synth._client.messages.create.assert_called_once()

    def test_synthesize_module_caches_result(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        synth.synthesize_module(simple_community)
        synth.synthesize_module(simple_community)  # Second call: should hit cache
        # LLM called exactly once
        assert synth._client.messages.create.call_count == 1

    def test_token_count_tracked(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        synth.synthesize_module(simple_community)
        assert synth.total_input_tokens == 100
        assert synth.total_output_tokens == 50

    def test_synthesize_module_text_nonempty(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        result = synth.synthesize_module(simple_community)
        assert len(result["text"]) > 0


class TestSynthesizerRepoLevel:
    def test_synthesize_repo_returns_dict(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        mod_descs = {"svc/community_0": "认证模块负责用户登录。"}
        result = synth.synthesize_repo("svc", mod_descs)
        assert isinstance(result, dict)
        assert "text" in result

    def test_synthesize_repo_caches(
        self, synth: Synthesizer
    ) -> None:
        mod_descs = {"c0": "desc"}
        synth.synthesize_repo("svc", mod_descs)
        synth.synthesize_repo("svc", mod_descs)
        assert synth._client.messages.create.call_count == 1


class TestSynthesizerFeatureLevel:
    def test_synthesize_feature_returns_dict(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        fg = {"community_ids": ["repo-a/community_0"], "repos": ["repo-a"]}
        communities = {"repo-a/community_0": simple_community}
        mod_texts = {"repo-a/community_0": "auth module"}
        result = synth.synthesize_feature(fg, communities, mod_texts)
        assert isinstance(result, dict)
        assert "text" in result

    def test_synthesize_feature_caches(
        self, synth: Synthesizer, simple_community: dict
    ) -> None:
        fg = {"community_ids": ["repo-a/community_0"], "repos": ["repo-a"]}
        communities = {"repo-a/community_0": simple_community}
        mod_texts = {"repo-a/community_0": "auth module"}
        synth.synthesize_feature(fg, communities, mod_texts)
        synth.synthesize_feature(fg, communities, mod_texts)
        assert synth._client.messages.create.call_count == 1


class TestSynthesizerAPIKey:
    def test_anthropic_missing_key_raises(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="anthropic", model="claude-opus-4-6", api_key="")
        with pytest.MonkeyPatch().context() as mp:
            mp.delenv("ANTHROPIC_API_KEY", raising=False)
            with pytest.raises(ValueError, match="API Key"):
                Synthesizer(cfg, cache)

    def test_anthropic_config_key_priority(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="anthropic", model="claude-opus-4-6", api_key="sk-from-config")
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("ANTHROPIC_API_KEY", "sk-from-env")
            s = Synthesizer(cfg, cache)
        assert s._client.api_key == "sk-from-config"

    def test_anthropic_env_key_fallback(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="anthropic", model="claude-opus-4-6", api_key="")
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("ANTHROPIC_API_KEY", "sk-from-env")
            s = Synthesizer(cfg, cache)
        assert s._client.api_key == "sk-from-env"

    def test_openai_missing_key_raises(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="")
        with pytest.MonkeyPatch().context() as mp:
            mp.delenv("OPENAI_API_KEY", raising=False)
            with pytest.raises(ValueError, match="API Key"):
                Synthesizer(cfg, cache)

    def test_openai_env_key_used(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="")
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("OPENAI_API_KEY", "sk-openai-test")
            s = Synthesizer(cfg, cache)
        assert s._client.api_key == "sk-openai-test"

    def test_openai_compatible_requires_base_url(self, cache: Cache) -> None:
        cfg = LLMConfig(provider="openai-compatible", model="glm-4", api_key="key", base_url="")
        with pytest.raises(ValueError, match="base_url"):
            Synthesizer(cfg, cache)

    def test_openai_compatible_with_base_url(self, cache: Cache) -> None:
        cfg = LLMConfig(
            provider="openai-compatible", model="glm-4-flash",
            api_key="glm-key",
            base_url="https://open.bigmodel.cn/api/paas/v4/",
        )
        s = Synthesizer(cfg, cache)
        assert s._client.api_key == "glm-key"
        assert "bigmodel" in str(s._client.base_url)


class TestSynthesizerLanguage:
    def test_zh_uses_chinese_system_prompt(
        self, llm_cfg: LLMConfig, cache: Cache
    ) -> None:
        s = Synthesizer(llm_cfg, cache, language="zh")
        assert "中文" in s._system

    def test_en_uses_english_system_prompt(
        self, llm_cfg: LLMConfig, cache: Cache
    ) -> None:
        s = Synthesizer(llm_cfg, cache, language="en")
        assert "English" in s._system

    def test_invalid_language_falls_back_to_zh(
        self, llm_cfg: LLMConfig, cache: Cache
    ) -> None:
        s = Synthesizer(llm_cfg, cache, language="fr")
        assert s.lang == "zh"
