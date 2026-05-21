"""Output rendering: Markdown and JSON.

Markdown structure:

  # 代码功能描述报告
  （元信息：生成时间、分析仓库列表、统计数据）

  ## 一、各服务功能描述
    ### {repo_name} — {服务名称}
      （服务级描述）
      #### 模块详情
        ##### {module_label}
          （模块级描述）

  ## 二、跨服务业务功能
    ### 业务功能 {N}（涉及：svc_a, svc_b）
      （特性级描述）
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render(
    result: dict[str, Any],
    output_dir: Path,
    fmt: str = "markdown",
    language: str = "zh",
) -> list[Path]:
    """Write output files and return list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if fmt in ("markdown", "both"):
        md_path = output_dir / "feature_description.md"
        md_path.write_text(
            _render_markdown(result, language), encoding="utf-8"
        )
        written.append(md_path)

    if fmt in ("json", "both"):
        json_path = output_dir / "feature_description.json"
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written.append(json_path)

    return written


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _render_markdown(result: dict[str, Any], language: str) -> str:
    zh = language == "zh"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    repos = result.get("repos", {})
    communities = result.get("communities", {})
    repo_descs: dict[str, str] = result.get("repo_descriptions", {})
    module_descs: dict[str, str] = result.get("module_descriptions", {})
    feature_descs: list[dict[str, Any]] = result.get("feature_descriptions", [])

    repo_names = sorted(repos.keys())
    total_modules = len(communities)
    total_features = len(feature_descs)

    lines: list[str] = []

    # --- Title ---
    lines += [
        f"# {'代码功能描述报告' if zh else 'Code Feature Description Report'}",
        "",
        f"> {'生成时间' if zh else 'Generated'}: {now}  ",
        f"> {'分析仓库' if zh else 'Repositories'}: {', '.join(repo_names)}  ",
        f"> {'模块数量' if zh else 'Modules'}: {total_modules}  "
        f"| {'跨服务功能' if zh else 'Cross-service features'}: {total_features}",
        "",
        "---",
        "",
    ]

    # --- Table of Contents ---
    lines += [
        f"## {'目录' if zh else 'Contents'}",
        "",
        f"- [{'一、各服务功能描述' if zh else '1. Service Descriptions'}](#{'各服务功能描述' if zh else 'service-descriptions'})",
    ]
    for repo_name in repo_names:
        anchor = _anchor(repo_name)
        lines.append(f"  - [{repo_name}](#{anchor})")
    lines += [
        f"- [{'二、跨服务业务功能' if zh else '2. Cross-Service Features'}](#{'跨服务业务功能' if zh else 'cross-service-features'})",
        "",
        "---",
        "",
    ]

    # ===================================================================
    # Section 1: Per-repo descriptions
    # ===================================================================
    lines += [
        f"## {'一、各服务功能描述' if zh else '1. Service Descriptions'}",
        "",
    ]

    for repo_name in repo_names:
        repo_info = repos[repo_name]
        comm_ids = sorted(repo_info.get("community_ids", []))

        lines += [
            f"### {repo_name}",
            "",
        ]

        # Repo-level description
        repo_desc = repo_descs.get(repo_name, "")
        if repo_desc:
            lines += [repo_desc, ""]

        # Module details
        if comm_ids:
            lines += [
                f"#### {'模块详情' if zh else 'Module Details'}",
                "",
            ]
            for cid in comm_ids:
                comm = communities.get(cid, {})
                mod_label = comm.get("label", cid.split("/")[-1])
                mod_size = comm.get("size", 0)
                lines += [
                    f"##### {mod_label}",
                    "",
                    f"> {'代码实体数量' if zh else 'Code entities'}: {mod_size}  "
                    f"| {'社区ID' if zh else 'Community'}: `{cid}`",
                    "",
                ]
                mod_desc = module_descs.get(cid, "")
                if mod_desc:
                    lines += [mod_desc, ""]
                else:
                    lines += [
                        f"*{'（描述生成失败）' if zh else '(description unavailable)'}*",
                        "",
                    ]

        lines += ["---", ""]

    # ===================================================================
    # Section 2: Cross-repo features
    # ===================================================================
    lines += [
        f"## {'二、跨服务业务功能' if zh else '2. Cross-Service Features'}",
        "",
    ]

    if not feature_descs:
        lines += [
            f"> {'未检测到跨服务调用关系，或所有仓库相互独立。' if zh else 'No cross-service relationships detected.'}",
            "",
        ]
    else:
        for i, feat in enumerate(feature_descs, 1):
            repos_involved = feat.get("repos", [])
            comm_ids = feat.get("community_ids", [])
            desc = feat.get("description", "")

            label_hint = (
                f"{'涉及服务' if zh else 'Services'}: {', '.join(repos_involved)}"
            )
            lines += [
                f"### {'业务功能' if zh else 'Feature'} {i}  ·  {label_hint}",
                "",
            ]

            if desc:
                lines += [desc, ""]
            else:
                lines += [
                    f"*{'（描述生成失败）' if zh else '(description unavailable)'}*",
                    "",
                ]

            # Module cross-reference
            lines += [
                f"<details><summary>{'涉及的模块' if zh else 'Involved modules'}</summary>",
                "",
            ]
            for cid in comm_ids:
                comm = communities.get(cid, {})
                lines.append(
                    f"- `{cid}` — {comm.get('label', '')} ({comm.get('repo', '')})"
                )
            lines += ["", "</details>", "", "---", ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _anchor(text: str) -> str:
    """Convert a heading text to a GitHub-compatible anchor."""
    return text.lower().replace(" ", "-").replace("/", "").replace(".", "")
