---
name: synth-card
description: "Generate structured feature cards from a codebase. Use when the user wants to understand what a module/feature does, explore a repo's functionality, or produce shareable feature cards. Trigger: /synth-card"
trigger: /synth-card
---

# /synth-card

Generate structured **功能卡片 (feature cards)** — a concise, readable summary of what a code module does, its key components, and how it connects to the rest of the system.

## Usage

```
/synth-card                      # detect current repo, ask which feature to card
/synth-card auth                 # card for anything matching "auth"
/synth-card user login flow      # card for user login related code
/synth-card --all                # generate cards for every detected module
/synth-card <path>               # run on a specific directory
/synth-card <path> <feature>     # specific path + specific feature
```

---

## What You Must Do When Invoked

Parse the arguments after `/synth-card`:
- `--help` / `-h` → print the Usage block above and stop.
- First token that looks like a path (starts with `.` `/` `~` or contains `/`) → that is the **repo path**; any remaining text is the **feature query**.
- Otherwise the whole argument is the **feature query**; repo path defaults to `.`.
- `--all` flag anywhere → **batch mode** (generate all modules, no prompting).

Then execute the steps below in order.

---

## Step 0 — Locate the skill script

```bash
SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/synth-card"
SYNTH_GRAPH="$SKILL_DIR/synth_graph.py"
```

---

## Step 1 — Verify the skill script is installed

```bash
test -f "$SYNTH_GRAPH" || {
  echo "error: synth_graph.py not found at $SYNTH_GRAPH"
  echo "Please install the synth-card skill:"
  echo "  curl -fsSL https://raw.githubusercontent.com/lucaslam92/Synth/main/install.sh | bash"
  echo "  # or manually:"
  echo "  mkdir -p $SKILL_DIR"
  echo "  cp /path/to/synth/skills/synth-card/synth_graph.py $SKILL_DIR/"
  exit 1
}
```

If this fails, tell the user how to install the skill and stop.

---

## Step 2 — Find the repository root

```bash
python3 - <<'PYEOF'
import json
from pathlib import Path

start = Path("RESOLVED_PATH_FROM_ARGS")   # replace with actual path, default "."
start = start.resolve()

def find_repo_root(p: Path):
    for candidate in [p, *p.parents]:
        if (candidate / ".git").exists():
            return candidate
    return p  # fallback: use the path itself

root = find_repo_root(start)
has_source = (
    any(root.rglob("*.py")) or
    any(root.rglob("*.ts")) or
    any(root.rglob("*.go")) or
    any(root.rglob("*.rs")) or
    any(root.rglob("*.java"))
)
print(json.dumps({
    "repo_root": str(root),
    "repo_name": root.name,
    "has_graph": (root / "graphify-out" / "graph.json").exists(),
    "has_source": has_source,
}))
PYEOF
```

Save the JSON output. If `has_source` is false, tell the user no supported source files were found and stop.

---

## Step 3 — Build the code graph (if not already built)

Check `has_graph` from Step 2.

**If graph already exists** → skip to Step 4.

**If graph is missing** → tell the user "正在分析代码结构，首次运行需要一点时间…" then run:

```bash
python3 "$SYNTH_GRAPH" graph-build "$REPO_ROOT"
```

> `graph-build` requires `graphifyy` to be installed: `pip install graphifyy`
>
> If the command fails with an import error, ask the user to run `pip install graphifyy` first.

If this fails, show the error and stop.

---

## Step 4 — Show detected modules

```bash
python3 "$SYNTH_GRAPH" graph-list "$REPO_ROOT"
```

This prints a table of all detected modules (community_id, label, size, files).

---

## Step 5 — Determine scope

### Case A — Feature query provided

```bash
python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --feature "<feature_query>"
```

Read the JSON output:
- `"action": "generate_card"` → proceed to Step 6 with this data.
- `"action": "no_match"` → tell the user no nodes matched, show the modules list from the JSON, ask which module to use.

### Case B — No query provided (interactive)

The module table from Step 4 is already shown. Ask the user:

> 请选择要生成功能卡片的模块（输入序号、模块名，或输入"全部"生成所有模块）：

Wait for their reply, then:
- Number or name → resolve to that module's `community_id` → run:
  ```bash
  python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --module <community_id>
  ```
- "全部" / "all" / or `--all` was in the original invocation → **Batch mode**: run `card-data` for each module in sequence.

### Case C — `--all` flag

Run `card-data` for each community_id from `graph-list --json` output:

```bash
python3 "$SYNTH_GRAPH" graph-list "$REPO_ROOT" --json
```

Then for each module:
```bash
python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --module <community_id>
```

---

## Step 6 — Generate the feature card

Using the JSON from `card-data` (which has `action: "generate_card"`), generate a markdown card in this exact format:

```markdown
## 🃏 功能卡片：{label}

| 属性 | 值 |
|------|-----|
| 仓库 | {repo} |
| 主要路径 | {nodes[0].source_file 的父目录} |
| 组件数量 | {node_count} 个 |

### 功能描述

{一段话，面向第一次接触这个代码库的开发者，说清楚这个模块是干什么的。
 必须具体：提到关键类/函数名，解释数据流向，指出重要的设计模式或算法。
 不要泛泛而谈。200字以内。}

### 核心组件

{bullet list，每个最重要的 class/function 一行，附一句话说明其职责}

### 内部调用关系

{根据 edges 数据，简述主要组件之间怎么互相调用。如果 edges 为空，注明"暂无调用关系数据"。}

### 对外依赖 & 被依赖

{如果节点的 source_file 或 label 里能看出跨模块 import，列出来。看不出来就省略这一节。}
```

**规则：**
- 只根据 `nodes` 和 `edges` 里的数据生成，不要凭空编造功能。
- `repo` 含中文或用户用中文提问 → 用中文生成；否则用英文。
- 每张卡片独立完整，不要引用"如上所述"之类的表述。

---

## Step 7 — Output

**Single card** → print the markdown directly.

**Batch mode** (`--all` or user chose "全部"):
- Create directory `synth-out/cards/` if it doesn't exist.
- Write each card to `synth-out/cards/{label}.md`.
- After all cards are written, print:

```
✓ 生成完成，共 N 张功能卡片
  → synth-out/cards/auth.md
  → synth-out/cards/orders.md
  ...
```

---

## Error reference

| 情况 | 处理 |
|------|------|
| `synth_graph.py` 未安装 | 打印安装命令，停止 |
| `graphifyy` 未安装 | 提示 `pip install graphifyy`，停止 |
| 路径不存在 | 提示用户检查路径 |
| 无支持的源文件 | 说明支持的语言列表 |
| graph-build 失败 | 显示错误，建议手动运行 `pip install graphifyy` 后重试 |
| 关键词无匹配 | 展示模块列表，让用户选 |
