"""Synth CLI entry point.

Commands:
  synth init          Create a template synth.toml in the current directory
  synth run           Full synthesis pipeline (load → link → aggregate → synthesize → render)
  synth show          Print the last generated report to stdout
  synth clean         Remove cache (optionally by level)
  synth status        Show cache stats and last-run summary
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="synth",
    help="Cross-repository code graph → natural language feature description synthesizer.",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    output: Path = typer.Option(Path("synth.toml"), "--output", "-o", help="Config file path"),
) -> None:
    """Create a template synth.toml in the current directory."""
    if output.exists():
        if not typer.confirm(f"{output} already exists. Overwrite?"):
            raise typer.Abort()

    template = Path(__file__).parent.parent / "synth.toml.example"
    if template.exists():
        output.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        output.write_text(_DEFAULT_CONFIG, encoding="utf-8")

    console.print(f"[green]✓[/green] Created {output}")
    console.print("Edit the [[repos]] entries and then run: [bold]synth run[/bold]")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    config: Path = typer.Option(Path("synth.toml"), "--config", "-c", help="Config file"),
    force: bool = typer.Option(False, "--force", "-f", help="Ignore cache, regenerate all"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress"),
) -> None:
    """Run the full synthesis pipeline."""
    from .aggregate import build_hierarchy, detect_communities, merge_graphs
    from .cache import Cache
    from .config import load_config
    from .ingest import load_all_graphs
    from .link import find_cross_repo_edges
    from .render import render
    from .synthesize import Synthesizer

    # --- Config ---
    try:
        cfg = load_config(config)
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1)

    if force:
        cache = Cache(cfg.cache.dir, enabled=False)
    else:
        cache = Cache(cfg.cache.dir, enabled=cfg.cache.enabled)

    synth = Synthesizer(cfg.llm, cache, cfg.output.language)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=not verbose,
    ) as progress:

        # --- Step 1: Load graphs ---
        task = progress.add_task("加载图谱…", total=None)
        try:
            graphs = load_all_graphs(cfg.repos)
        except FileNotFoundError as e:
            err_console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
        progress.update(task, description=f"✓ 加载完成 — {len(graphs)} 个仓库")

        # --- Step 2: Cross-repo linking ---
        progress.update(task, description="检测跨仓库关联…")
        cross_edges = find_cross_repo_edges(graphs, cfg.repos)
        if verbose:
            console.print(f"  发现 {len(cross_edges)} 条跨仓库边")

        # --- Step 3: Merge + community detection ---
        progress.update(task, description="合并图谱，检测社区…")
        merged = merge_graphs(graphs, cross_edges)
        node_to_community = detect_communities(merged)
        hierarchy = build_hierarchy(merged, node_to_community, graphs)

        communities = hierarchy["communities"]
        repos_map = hierarchy["repos"]
        feature_groups = hierarchy["feature_groups"]

        if verbose:
            console.print(
                f"  {len(communities)} 个模块社区，{len(feature_groups)} 个跨服务功能组"
            )

        # --- Step 4: Synthesize modules ---
        # Values are {"text": str, "code_map": dict}
        module_descriptions: dict[str, dict] = {}
        total_mods = len(communities)
        mod_task = progress.add_task(f"生成模块描述 (0/{total_mods})…", total=total_mods)

        for i, (cid, comm) in enumerate(communities.items(), 1):
            progress.update(
                mod_task,
                description=f"生成模块描述 ({i}/{total_mods}): {comm['label']}",
                advance=1,
            )
            module_descriptions[cid] = synth.synthesize_module(comm)

        # --- Step 5: Synthesize repos ---
        repo_descriptions: dict[str, dict] = {}
        repo_task = progress.add_task(f"生成服务描述 (0/{len(repos_map)})…", total=len(repos_map))

        for i, (repo_name, repo_info) in enumerate(repos_map.items(), 1):
            progress.update(
                repo_task,
                description=f"生成服务描述 ({i}/{len(repos_map)}): {repo_name}",
                advance=1,
            )
            # Pass plain text to repo synthesis — it summarises module texts
            repo_module_descs = {
                cid: module_descriptions[cid]["text"]
                for cid in repo_info["community_ids"]
                if cid in module_descriptions
            }
            repo_descriptions[repo_name] = synth.synthesize_repo(repo_name, repo_module_descs)

        # --- Step 6: Synthesize cross-repo features ---
        feature_descriptions: list[dict] = []
        if feature_groups:
            feat_task = progress.add_task(
                f"生成跨服务功能描述 (0/{len(feature_groups)})…",
                total=len(feature_groups),
            )
            # Plain-text view of module descriptions for feature synthesis
            module_texts = {cid: d["text"] for cid, d in module_descriptions.items()}
            for i, fg in enumerate(feature_groups, 1):
                progress.update(
                    feat_task,
                    description=f"生成跨服务功能描述 ({i}/{len(feature_groups)})",
                    advance=1,
                )
                desc = synth.synthesize_feature(fg, communities, module_texts)
                feature_descriptions.append({
                    "community_ids": fg["community_ids"],
                    "repos": fg["repos"],
                    "description": desc,
                })

        # --- Step 7: Render ---
        progress.update(task, description="写入输出文件…")
        result = {
            "repos": repos_map,
            "communities": dict(communities),  # node_ids kept for downstream use
            "repo_descriptions": repo_descriptions,
            "module_descriptions": module_descriptions,
            "feature_descriptions": feature_descriptions,
        }

        written = render(result, cfg.output.dir, cfg.output.format, cfg.output.language)
        progress.update(task, description="✓ 完成")

    # --- Summary ---
    console.print()
    console.print("[bold green]✓ 生成完成[/bold green]")
    for path in written:
        console.print(f"  → [cyan]{path}[/cyan]")

    stats = cache.stats
    console.print(
        f"\n缓存命中率: {stats['hit_rate']:.0%}  "
        f"({stats['hits']} 命中 / {stats['misses']} 未命中)"
    )
    console.print(
        f"Token 消耗: 输入 {synth.total_input_tokens:,}  输出 {synth.total_output_tokens:,}"
    )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@app.command()
def show(
    config: Path = typer.Option(Path("synth.toml"), "--config", "-c"),
) -> None:
    """Print the last generated Markdown report to stdout."""
    try:
        from .config import load_config
        cfg = load_config(config)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    md_path = cfg.output.dir / "feature_description.md"
    if not md_path.exists():
        err_console.print(f"[yellow]No report found at {md_path}[/yellow]")
        err_console.print("Run 'synth run' first.")
        raise typer.Exit(1)

    console.print(md_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


@app.command()
def clean(
    config: Path = typer.Option(Path("synth.toml"), "--config", "-c"),
    level: Optional[str] = typer.Argument(
        None,
        help="Cache level to clear: modules | repos | features (omit to clear all)",
    ),
) -> None:
    """Remove cached LLM outputs."""
    try:
        from .config import load_config
        from .cache import Cache
        cfg = load_config(config)
        cache = Cache(cfg.cache.dir)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    cache.clear(level)
    target = f"level '{level}'" if level else "all levels"
    console.print(f"[green]✓[/green] Cache cleared ({target})")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    config: Path = typer.Option(Path("synth.toml"), "--config", "-c"),
) -> None:
    """Show configuration and output status."""
    try:
        from .config import load_config
        cfg = load_config(config)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Repos table
    table = Table(title="配置的仓库", show_header=True)
    table.add_column("名称", style="cyan")
    table.add_column("类型")
    table.add_column("图谱路径")
    table.add_column("状态")
    for repo in cfg.repos:
        status_str = "[green]✓ 存在[/green]" if repo.graph.exists() else "[red]✗ 缺失[/red]"
        table.add_row(repo.name, repo.type, str(repo.graph), status_str)
    console.print(table)

    # Output
    md_path = cfg.output.dir / "feature_description.md"
    if md_path.exists():
        import os
        size = os.path.getsize(md_path)
        mtime = Path(md_path).stat().st_mtime
        from datetime import datetime
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        console.print(f"\n最后生成: [cyan]{ts}[/cyan]  |  文件大小: {size // 1024} KB")
    else:
        console.print("\n[yellow]尚未生成报告[/yellow]  —  运行 'synth run' 开始生成")

    # Cache
    import os
    cache_dir = cfg.cache.dir
    if cache_dir.exists():
        total = sum(1 for _ in cache_dir.rglob("*.json"))
        console.print(f"缓存条目数: {total}")


# ---------------------------------------------------------------------------
# Default config template (fallback if synth.toml.example not found)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = """\
# synth.toml — Synth configuration
# Run 'synth run' after editing this file.

[output]
language = "zh"        # zh | en
format   = "markdown"  # markdown | json | both
dir      = "synth-out"

[cache]
dir     = ".synth-cache"
enabled = true

[llm]
model      = "claude-opus-4-6"
max_tokens = 2048

# Add one [[repos]] block per repository.
# 'graph' points to the graphify-out/graph.json produced by graphify.
# 'packages' lists all package/module names this repo exports (used for
#  cross-repo import linking).

[[repos]]
name     = "my-service-a"
graph    = "../my-service-a/graphify-out/graph.json"
type     = "microservice"    # microservice | library | monorepo
packages = ["@company/my-service-a"]

[[repos]]
name     = "my-service-b"
graph    = "../my-service-b/graphify-out/graph.json"
type     = "microservice"
packages = ["@company/my-service-b"]

[[repos]]
name     = "shared-lib"
graph    = "../shared-lib/graphify-out/graph.json"
type     = "library"
packages = ["@company/shared-lib", "shared_lib"]
"""

if __name__ == "__main__":
    app()
