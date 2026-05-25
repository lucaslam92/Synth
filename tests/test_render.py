"""Tests for synth.render — Markdown and JSON output rendering."""

import json
from pathlib import Path

import pytest

from synth.render import render


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_result(feature_descriptions: list | None = None) -> dict:
    return {
        "repos": {
            "svc-a": {"name": "svc-a", "community_ids": ["svc-a/community_0"]},
        },
        "communities": {
            "svc-a/community_0": {
                "id": "svc-a/community_0",
                "label": "auth",
                "repo": "svc-a",
                "community_id": 0,
                "nodes": [],
                "node_ids": [],
                "size": 5,
            },
        },
        "repo_descriptions": {
            "svc-a": {"text": "svc-a is the auth service.", "code_map": {}},
        },
        "module_descriptions": {
            "svc-a/community_0": {"text": "Handles authentication logic.", "code_map": {}},
        },
        "feature_descriptions": feature_descriptions or [],
    }


def _two_repo_result() -> dict:
    result = _minimal_result()
    result["repos"]["svc-b"] = {"name": "svc-b", "community_ids": ["svc-b/community_0"]}
    result["communities"]["svc-b/community_0"] = {
        "id": "svc-b/community_0", "label": "orders", "repo": "svc-b",
        "community_id": 0, "nodes": [], "node_ids": [], "size": 3,
    }
    result["repo_descriptions"]["svc-b"] = {"text": "svc-b handles orders.", "code_map": {}}
    result["module_descriptions"]["svc-b/community_0"] = {
        "text": "Order processing.", "code_map": {}
    }
    result["feature_descriptions"] = [{
        "community_ids": ["svc-a/community_0", "svc-b/community_0"],
        "repos": ["svc-a", "svc-b"],
        "description": {"text": "Cross-repo feature: auth + orders.", "code_map": {}},
    }]
    return result


# ---------------------------------------------------------------------------
# Tests: file output
# ---------------------------------------------------------------------------


class TestRenderOutputFiles:
    def test_markdown_file_written(self, tmp_path: Path) -> None:
        written = render(_minimal_result(), tmp_path, fmt="markdown")
        assert len(written) == 1
        assert written[0].suffix == ".md"
        assert written[0].exists()

    def test_json_file_written(self, tmp_path: Path) -> None:
        written = render(_minimal_result(), tmp_path, fmt="json")
        assert len(written) == 1
        assert written[0].suffix == ".json"
        assert written[0].exists()

    def test_both_formats_written(self, tmp_path: Path) -> None:
        written = render(_minimal_result(), tmp_path, fmt="both")
        suffixes = {p.suffix for p in written}
        assert suffixes == {".md", ".json"}

    def test_output_dir_created_if_missing(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "nested" / "dir"
        render(_minimal_result(), out_dir)
        assert out_dir.exists()

    def test_json_is_valid(self, tmp_path: Path) -> None:
        written = render(_minimal_result(), tmp_path, fmt="json")
        content = written[0].read_text(encoding="utf-8")
        data = json.loads(content)  # Must not raise
        assert "repos" in data


class TestMarkdownContent:
    def _md(self, result: dict | None = None, language: str = "zh") -> str:
        import io
        from pathlib import Path
        tmp = Path("/tmp/synth_test_render")
        tmp.mkdir(exist_ok=True)
        written = render(result or _minimal_result(), tmp, fmt="markdown", language=language)
        return written[0].read_text(encoding="utf-8")

    def test_title_present_zh(self) -> None:
        md = self._md(language="zh")
        assert "代码功能描述报告" in md

    def test_title_present_en(self) -> None:
        md = self._md(language="en")
        assert "Code Feature Description Report" in md

    def test_repo_name_in_output(self) -> None:
        md = self._md()
        assert "svc-a" in md

    def test_module_description_in_output(self) -> None:
        md = self._md()
        assert "Handles authentication logic." in md

    def test_repo_description_in_output(self) -> None:
        md = self._md()
        assert "svc-a is the auth service." in md

    def test_toc_section_present(self) -> None:
        md = self._md()
        assert "目录" in md or "Contents" in md

    def test_no_cross_service_section_when_empty(self) -> None:
        md = self._md(_minimal_result(feature_descriptions=[]))
        # Should indicate no cross-service relationships
        assert "未检测到" in md or "No cross-service" in md

    def test_cross_service_feature_rendered(self) -> None:
        import io
        from pathlib import Path
        tmp = Path("/tmp/synth_test_render_cross")
        tmp.mkdir(exist_ok=True)
        written = render(_two_repo_result(), tmp, fmt="markdown", language="zh")
        md = written[0].read_text(encoding="utf-8")
        assert "Cross-repo feature" in md or "跨服务" in md
        assert "svc-a" in md
        assert "svc-b" in md

    def test_module_size_shown(self) -> None:
        md = self._md()
        assert "5" in md  # community size = 5

    def test_legacy_plain_string_descriptions_handled(self) -> None:
        """render must handle both dict {'text': ...} and plain str descriptions."""
        result = _minimal_result()
        # Downgrade to plain strings (old format)
        result["repo_descriptions"]["svc-a"] = "plain repo desc"
        result["module_descriptions"]["svc-a/community_0"] = "plain mod desc"
        import io
        from pathlib import Path
        tmp = Path("/tmp/synth_test_render_legacy")
        tmp.mkdir(exist_ok=True)
        written = render(result, tmp, fmt="markdown")
        md = written[0].read_text(encoding="utf-8")
        assert "plain repo desc" in md
        assert "plain mod desc" in md
