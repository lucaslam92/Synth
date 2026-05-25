"""Configuration loading from synth.toml."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            raise ImportError("Python < 3.11 requires 'tomli': pip install tomli")


@dataclass
class RepoConfig:
    """Configuration for a single repository input."""

    name: str
    # Path to graphify-out/graph.json (preferred) OR source code root directory.
    graph: Path
    # Relationship type hint — used to tune cross-repo linking heuristics.
    type: Literal["microservice", "library", "monorepo"] = "microservice"
    # Package/module names this repo exports (e.g. "@company/shared-utils", "shared_utils").
    # Used for import-based cross-repo edge detection.
    packages: list[str] = field(default_factory=list)


@dataclass
class OutputConfig:
    language: Literal["zh", "en"] = "zh"
    format: Literal["markdown", "json", "both"] = "markdown"
    dir: Path = Path("synth-out")


@dataclass
class CacheConfig:
    dir: Path = Path(".synth-cache")
    enabled: bool = True


@dataclass
class LLMConfig:
    # Provider 决定使用哪个 SDK 和鉴权方式：
    #   anthropic         — Anthropic SDK，支持 prompt caching（推荐，默认）
    #   openai            — OpenAI SDK，使用官方 OpenAI API
    #   openai-compatible — OpenAI SDK + 自定义 base_url，适配 GLM / DeepSeek /
    #                       Qwen / Ollama 等兼容 OpenAI 接口的服务
    provider: Literal["anthropic", "openai", "openai-compatible"] = "anthropic"
    model: str = "claude-opus-4-6"
    max_tokens: int = 2048
    # API Key 优先级：synth.toml [llm] api_key > 对应的环境变量
    #   anthropic         → ANTHROPIC_API_KEY
    #   openai            → OPENAI_API_KEY
    #   openai-compatible → api_key（必填，或 OPENAI_API_KEY 作为 fallback）
    api_key: str = ""
    # 仅 openai-compatible 需要填写，指向对应服务的 API 地址
    #   GLM:      https://open.bigmodel.cn/api/paas/v4/
    #   DeepSeek: https://api.deepseek.com/v1
    #   Qwen:     https://dashscope.aliyuncs.com/compatible-mode/v1
    #   Ollama:   http://localhost:11434/v1
    base_url: str = ""


@dataclass
class SynthConfig:
    repos: list[RepoConfig]
    output: OutputConfig = field(default_factory=OutputConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_config(path: Path = Path("synth.toml")) -> SynthConfig:
    """Load and validate a synth.toml config file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Run 'synth init' to create a template."
        )

    with open(path, "rb") as f:
        data = tomllib.load(f)

    repos: list[RepoConfig] = []
    for r in data.get("repos", []):
        if "name" not in r or "graph" not in r:
            raise ValueError("Each [[repos]] entry must have 'name' and 'graph' fields.")
        repos.append(
            RepoConfig(
                name=r["name"],
                graph=Path(r["graph"]),
                type=r.get("type", "microservice"),
                packages=r.get("packages", []),
            )
        )

    if not repos:
        raise ValueError("No [[repos]] entries found in config. Add at least one repo.")

    out = data.get("output", {})
    output = OutputConfig(
        language=out.get("language", "zh"),
        format=out.get("format", "markdown"),
        dir=Path(out.get("dir", "synth-out")),
    )

    c = data.get("cache", {})
    cache = CacheConfig(
        dir=Path(c.get("dir", ".synth-cache")),
        enabled=c.get("enabled", True),
    )

    llm = data.get("llm", {})
    provider = llm.get("provider", "anthropic")
    if provider not in ("anthropic", "openai", "openai-compatible"):
        raise ValueError(
            f"[llm] provider 无效值: {provider!r}\n"
            "可选值: anthropic | openai | openai-compatible"
        )
    llm_cfg = LLMConfig(
        provider=provider,
        model=llm.get("model", "claude-opus-4-6"),
        max_tokens=llm.get("max_tokens", 2048),
        api_key=llm.get("api_key", ""),
        base_url=llm.get("base_url", ""),
    )

    return SynthConfig(repos=repos, output=output, cache=cache, llm=llm_cfg)
