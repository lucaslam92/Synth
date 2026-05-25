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
    model: str = "claude-opus-4-6"
    max_tokens: int = 2048
    # API Key 优先级：synth.toml [llm] api_key > ANTHROPIC_API_KEY 环境变量
    # 留空则自动从环境变量读取
    api_key: str = ""


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
    llm_cfg = LLMConfig(
        model=llm.get("model", "claude-opus-4-6"),
        max_tokens=llm.get("max_tokens", 2048),
        api_key=llm.get("api_key", ""),
    )

    return SynthConfig(repos=repos, output=output, cache=cache, llm=llm_cfg)
