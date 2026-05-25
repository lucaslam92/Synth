"""Hierarchical LLM synthesis of natural language descriptions.

Three synthesis levels, bottom-up:

  Level 1 — Module (community)
    Input : node labels + internal edges (AST-derived, no LLM needed for raw data)
    Output: structured Chinese/English description of the module's responsibilities

  Level 2 — Repository
    Input : all module descriptions for the repo + inter-module edges
    Output: service-level description with module map and collaboration summary

  Level 3 — Cross-repo Feature
    Input : module descriptions from multiple repos + cross-repo edges
    Output: end-to-end business feature description naming all involved services

Cache key at each level = SHA256(sorted representation of inputs), so unchanged
modules reuse their cached description and only changed modules incur LLM calls.

Prompt caching (Anthropic ephemeral cache) is applied to the system prompt to
reduce cost on repeated calls within a single run.
"""

from __future__ import annotations

import os
import re
from typing import Any

import anthropic

from .cache import Cache
from .config import LLMConfig

# ---------------------------------------------------------------------------
# System prompts (cached via Anthropic prompt caching)
# ---------------------------------------------------------------------------

_SYSTEM = {
    "zh": (
        "你是一个专业的代码架构分析助手，擅长从代码图谱数据中提取和描述软件功能。\n"
        "你的任务是根据提供的代码结构信息，生成清晰、准确、全面的功能描述。\n"
        "要求：\n"
        "- 覆盖全面，不遗漏任何有意义的功能细节\n"
        "- 面向技术人员，表达准确，层次清晰\n"
        "- 避免泛泛而谈，每条描述都应具体说明做什么、怎么做\n"
        "- 始终使用中文回答"
    ),
    "en": (
        "You are a professional code architecture analysis assistant specializing in "
        "extracting and describing software functionality from code graph data.\n"
        "Requirements:\n"
        "- Be comprehensive — do not omit any meaningful functional detail\n"
        "- Target technical audiences: precise language, clear hierarchy\n"
        "- Avoid vague generalisations; each statement should explain what and how\n"
        "- Always respond in English"
    ),
}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_MODULE_PROMPT = {
    "zh": """\
以下是代码模块 "{label}" 的结构信息，来自仓库 "{repo}"。

## 代码实体（共 {count} 个）
{nodes}

## 内部关系
{edges}

请生成该模块的功能描述，格式严格如下（不要省略任何一节）：

**模块名称**：（为该模块取一个准确的中文名称，体现其职责）

**职责概述**：（2-3 句话，说明该模块的整体定位和核心职责）

**核心功能点**：
（列出所有有意义的功能点，每条以"- "开头，具体说明该功能做什么，不少于 3 条，不多于 12 条）

**关键实体说明**：
（对模块中最重要的 2-5 个类/函数，逐一说明其具体作用）

**内部交互说明**：
（描述模块内各组件之间的调用/依赖关系，说明数据或控制流如何流转）
""",
    "en": """\
The following is the structure of code module "{label}" from repository "{repo}".

## Code Entities ({count} total)
{nodes}

## Internal Relationships
{edges}

Generate a module description strictly following this format (do not omit any section):

**Module Name**: (an accurate name reflecting its responsibility)

**Responsibility Summary**: (2-3 sentences on its overall role and core responsibilities)

**Core Features**:
(List all meaningful features, each starting with "- ", explain what each does, 3-12 items)

**Key Entity Descriptions**:
(For the 2-5 most important classes/functions, describe each one's specific role)

**Internal Interaction Summary**:
(Describe call/dependency relationships between components; how data or control flows)
""",
}

_REPO_PROMPT = {
    "zh": """\
以下是服务 "{repo}" 的所有模块功能描述：

{module_descriptions}

请生成该服务的整体功能描述，格式严格如下：

**服务名称**：（为该服务取一个准确的中文名称）

**服务定位**：（2-3 句话说明该服务的整体职责和在系统中的角色）

**功能模块总览**：
（按功能域列出所有模块，格式：- **模块名**：核心职责一句话概括）

**核心业务能力**：
（从业务视角出发，列出该服务提供的所有关键业务能力，不少于 3 条）

**模块间协作关系**：
（描述各模块之间的主要依赖和调用关系，说明整体工作机制）

**对外暴露的接口/能力**：
（描述该服务对其他服务或外部系统暴露的主要接口、事件或能力）
""",
    "en": """\
The following are descriptions of all modules in service "{repo}":

{module_descriptions}

Generate the overall service description strictly following this format:

**Service Name**: (an accurate name reflecting the service's responsibility)

**Service Role**: (2-3 sentences on overall responsibility and role in the system)

**Module Overview**:
(List all modules by functional domain: - **Module name**: one-line responsibility)

**Core Business Capabilities**:
(From a business perspective, list all key capabilities this service provides, ≥3 items)

**Inter-Module Collaboration**:
(Describe main dependencies and call relationships between modules)

**Exposed Interfaces/Capabilities**:
(Describe the main APIs, events, or capabilities this service exposes to others)
""",
}

_FEATURE_PROMPT = {
    "zh": """\
以下是来自多个服务的一组相关模块，它们之间存在跨服务调用或依赖关系。

## 涉及的模块
{module_descriptions}

## 跨服务调用关系
{cross_edges}

请识别这些模块共同实现的业务功能，并生成描述，格式严格如下：

**业务功能名称**：（识别出一个准确的端到端业务功能名称，体现业务价值）

**功能描述**：（3-5 句话，描述这个业务功能的完整定义和价值）

**端到端执行流程**：
（用有序步骤描述完整的业务流程，每步说明哪个服务/模块做了什么）

**各服务角色分工**：
（逐服务说明它在该功能中的具体职责）

**关键数据/事件流**：
（描述该业务流程中的核心数据对象或事件如何在各服务间流转）

**边界与依赖**：
（说明该功能的前提条件、外部依赖或触发条件）
""",
    "en": """\
The following is a set of related modules from multiple services with cross-service
calls or dependencies between them.

## Involved Modules
{module_descriptions}

## Cross-Service Call Relationships
{cross_edges}

Identify the business feature these modules collectively implement, following this format:

**Business Feature Name**: (an end-to-end feature name reflecting business value)

**Feature Description**: (3-5 sentences fully defining the feature and its value)

**End-to-End Execution Flow**:
(Ordered steps describing the complete business flow; each step: which service/module does what)

**Service Role Division**:
(For each service, describe its specific responsibility in this feature)

**Key Data/Event Flow**:
(Describe how core data objects or events flow between services)

**Boundaries and Dependencies**:
(Prerequisites, external dependencies, or trigger conditions for this feature)
""",
}


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


class Synthesizer:
    def __init__(self, llm: LLMConfig, cache: Cache, language: str = "zh") -> None:
        self.llm = llm
        self.cache = cache
        self.lang = language if language in ("zh", "en") else "zh"
        self._client = self._build_client(llm)
        self._system = _SYSTEM[self.lang]
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @staticmethod
    def _build_client(llm: LLMConfig) -> anthropic.Anthropic:
        """Resolve API key and return an Anthropic client.

        Priority:
          1. synth.toml [llm] api_key
          2. ANTHROPIC_API_KEY environment variable

        Raises a clear ValueError if neither is available.
        """
        api_key = llm.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "未找到 Anthropic API Key。请通过以下任意方式提供：\n"
                "  方式 1 — 环境变量（推荐）:\n"
                "    export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  方式 2 — 写入 synth.toml:\n"
                "    [llm]\n"
                "    api_key = \"sk-ant-...\"\n"
                "申请 API Key: https://console.anthropic.com/settings/keys"
            )
        return anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Level 1: Module
    # ------------------------------------------------------------------

    def synthesize_module(self, community: dict[str, Any]) -> dict[str, Any]:
        """Generate description for a single community/module.

        Returns {"text": str, "code_map": dict} where code_map links each
        described feature/entity to its source code location and snippet.
        """
        cache_key = _module_cache_key(community)
        cached = self.cache.get("modules", cache_key)
        if cached:
            if "text" in cached:
                return cached
            # migrate old cache format
            if "description" in cached:
                return {"text": cached["description"], "code_map": {}}

        nodes_text = _format_nodes(community["nodes"])
        edges_text = _format_edges(community["internal_edges"]) or (
            "  （无内部调用关系）" if self.lang == "zh" else "  (no internal call relationships)"
        )

        prompt = _MODULE_PROMPT[self.lang].format(
            label=community["label"],
            repo=community["repo"],
            count=len(community["nodes"]),
            nodes=nodes_text,
            edges=edges_text,
        )

        text = self._call(prompt)
        code_map = _build_code_map(text, community["nodes"])
        result = {"text": text, "code_map": code_map}
        self.cache.set("modules", cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Level 2: Repository
    # ------------------------------------------------------------------

    def synthesize_repo(
        self,
        repo_name: str,
        module_descriptions: dict[str, str],
    ) -> dict[str, Any]:
        """Generate repo-level description from all its module descriptions.

        module_descriptions values must be plain text strings (extract .text
        from synthesize_module results before calling).
        """
        cache_key = {
            "repo": repo_name,
            "modules": sorted(module_descriptions.items()),
        }
        cached = self.cache.get("repos", cache_key)
        if cached:
            if "text" in cached:
                return cached
            if "description" in cached:
                return {"text": cached["description"], "code_map": {}}

        sep = "\n\n---\n\n"
        mod_text = sep.join(
            f"### [{cid.split('/')[-1]}] {cid}\n\n{desc}"
            for cid, desc in sorted(module_descriptions.items())
        )

        prompt = _REPO_PROMPT[self.lang].format(
            repo=repo_name,
            module_descriptions=mod_text,
        )

        text = self._call(prompt)
        result = {"text": text, "code_map": {}}
        self.cache.set("repos", cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Level 3: Cross-repo feature
    # ------------------------------------------------------------------

    def synthesize_feature(
        self,
        feature_group: dict[str, Any],
        communities: dict[str, dict[str, Any]],
        module_descriptions: dict[str, str],
    ) -> dict[str, Any]:
        """Generate end-to-end cross-repo feature description.

        module_descriptions values must be plain text strings.
        """
        comm_ids = feature_group["community_ids"]
        cache_key = {
            "community_ids": sorted(comm_ids),
            "module_descs": sorted(
                (cid, module_descriptions.get(cid, ""))
                for cid in comm_ids
            ),
        }
        cached = self.cache.get("features", cache_key)
        if cached:
            if "text" in cached:
                return cached
            if "description" in cached:
                return {"text": cached["description"], "code_map": {}}

        sep = "\n\n---\n\n"
        mod_text = sep.join(
            f"### [{communities[cid]['repo']}] {communities[cid]['label']}\n\n"
            + module_descriptions.get(cid, "(暂无描述)" if self.lang == "zh" else "(no description)")
            for cid in sorted(comm_ids)
            if cid in communities
        )

        all_cross: list[dict] = []
        for cid in comm_ids:
            if cid in communities:
                all_cross.extend(communities[cid].get("cross_repo_edges", []))
        cross_text = _format_cross_edges(all_cross[:30], self.lang)

        prompt = _FEATURE_PROMPT[self.lang].format(
            module_descriptions=mod_text,
            cross_edges=cross_text,
        )

        text = self._call(prompt)
        result = {"text": text, "code_map": {}}
        self.cache.set("features", cache_key, result)
        return result

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call(self, user_prompt: str) -> str:
        response = self._client.messages.create(
            model=self.llm.model,
            max_tokens=self.llm.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self._system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        usage = response.usage
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        return response.content[0].text


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _module_cache_key(community: dict[str, Any]) -> dict:
    return {
        "nodes": sorted(n["label"] for n in community["nodes"]),
        "edges": sorted(
            f"{e['source']}-{e['relation']}-{e['target']}"
            for e in community["internal_edges"]
        ),
    }


def _format_nodes(nodes: list[dict]) -> str:
    lines = []
    for n in nodes:
        label = n.get("label", "")
        ftype = n.get("file_type", "")
        sf = n.get("source_file", "")
        line = n.get("line", 0)
        location = f"{sf}:{line}" if sf else ""
        lines.append(f"  - `{label}` ({ftype}){f'  —  {location}' if location else ''}")
    return "\n".join(lines) or "  （无实体信息）"


def _format_edges(edges: list[dict]) -> str:
    lines = []
    seen: set[str] = set()
    for e in edges:
        key = f"{e['source']} →[{e['relation']}]→ {e['target']}"
        if key not in seen:
            seen.add(key)
            lines.append(f"  - {key}")
    return "\n".join(lines)


def _format_cross_edges(edges: list[dict], lang: str) -> str:
    if not edges:
        return "  （无跨服务调用）" if lang == "zh" else "  (no cross-service calls)"
    lines = []
    seen: set[str] = set()
    for e in edges:
        src_repo = e.get("src_repo", "?")
        tgt_repo = e.get("tgt_repo", "?")
        relation = e.get("relation", "calls")
        key = f"[{src_repo}] →[{relation}]→ [{tgt_repo}]"
        if key not in seen:
            seen.add(key)
            lines.append(f"  - {key}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# code_map building
# ---------------------------------------------------------------------------

# Minimum label length to avoid matching noise words ("id", "db", etc.)
_MIN_LABEL_LEN = 4

# Section headers that introduce entity names (used to extract entity keys)
_ENTITY_SECTION_RE = re.compile(
    r"(?:\*\*关键实体说明\*\*|\*\*Key Entity Descriptions?\*\*)[^\n]*\n(.*?)(?=\n\*\*|\Z)",
    re.S,
)
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$", re.MULTILINE)
# Backtick or bold entity name at the start of a bullet or line
_ENTITY_NAME_RE = re.compile(r"(?:^|\n)[^`\n]*`([A-Za-z][A-Za-z0-9_]{3,})`|"
                              r"(?:^|\n)\s*[-*]\s*\*\*([A-Za-z][A-Za-z0-9_]{3,})\*\*")


def _build_code_map(text: str, nodes: list[dict]) -> dict[str, list[dict]]:
    """Map description phrases → code locations.

    Keys are bullet-point texts and entity names extracted from the description.
    Values are lists of matching node references {node_id, file, line, snippet}.
    Nodes with no source_file are excluded.
    """
    # Label → node lookup (only nodes that have a source file)
    label_index: dict[str, dict] = {
        n["label"]: n for n in nodes
        if n.get("label") and n.get("source_file") and len(n["label"]) >= _MIN_LABEL_LEN
    }
    if not label_index:
        return {}

    code_map: dict[str, list[dict]] = {}

    # 1. Bullet points: each bullet becomes a key; find any node labels inside it
    for m in _BULLET_RE.finditer(text):
        bullet = m.group(1).strip()
        refs = _nodes_mentioned_in(bullet, label_index)
        if refs:
            code_map[bullet] = refs

    # 2. Entity names: extract from backtick / bold tokens anywhere in the text
    for m in _ENTITY_NAME_RE.finditer(text):
        entity = m.group(1) or m.group(2)
        if entity and entity in label_index:
            ref = _node_ref(label_index[entity])
            existing = code_map.setdefault(entity, [])
            if ref not in existing:
                existing.append(ref)

    return code_map


def _nodes_mentioned_in(text: str, label_index: dict[str, dict]) -> list[dict]:
    """Return refs for every label that appears as a substring of text."""
    seen_ids: set[str] = set()
    refs: list[dict] = []
    for label, node in label_index.items():
        if label in text:
            ref = _node_ref(node)
            key = ref["node_id"]
            if key not in seen_ids:
                seen_ids.add(key)
                refs.append(ref)
    return refs


def _node_ref(node: dict) -> dict:
    return {
        "node_id": node.get("id", node.get("label", "")),
        "file": node.get("source_file", ""),
        "line": node.get("line", 0),
        "snippet": node.get("snippet", ""),
    }
