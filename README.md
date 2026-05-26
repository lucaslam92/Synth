# synth-card

[Claude Code](https://claude.ai/code) skill — 为任意代码仓库生成结构化**功能卡片**。

在 Claude Code 中输入 `/synth-card`，即可获得当前仓库某个模块的简洁描述：它是干什么的、有哪些核心组件、组件之间如何调用。

---

## 安装

```bash
git clone https://github.com/lucaslam92/Synth
cd synth
./install.sh
```

> 需要 Python 3.10+ 和 [graphifyy](https://github.com/safishamsi/graphify)（`graph-build` 步骤用到，自动安装）。

安装完成后，重启 Claude Code，即可使用 `/synth-card`。

---

## 使用方法

```
/synth-card                      # 检测当前仓库，交互式选择模块
/synth-card auth                 # 生成与 "auth" 相关的功能卡片
/synth-card user login flow      # 按关键词查找模块
/synth-card --all                # 批量生成所有模块卡片
/synth-card ~/my-repo            # 指定仓库路径
/synth-card ~/my-repo ingest     # 指定路径 + 关键词
```

**示例输出：**

```markdown
## 🃏 功能卡片：synth/ingest

| 属性 | 值 |
|------|-----|
| 仓库 | my-service |
| 主要路径 | synth/ingest |
| 组件数量 | 12 个 |

### 功能描述
ingest 模块负责加载代码图谱数据 ...

### 核心组件
- `load_repo_graph(repo)` — 加载单个仓库的 graph.json，如不存在则自动构建
- `_auto_build_graph(repo)` — 调用 graphify API 从源码提取 AST 图谱
...
```

---

## 仓库结构

```
skills/
  synth-card/
    SKILL.md          ← Claude Code skill 定义（安装后复制到 ~/.claude/skills/synth-card/）
    synth_graph.py    ← 独立 Python 脚本（graph-build / graph-list / card-data 等子命令）
    requirements.txt  ← 依赖声明（graphifyy>=0.8.0）
install.sh            ← 一键安装脚本
```

### synth_graph.py 子命令

`synth_graph.py` 是 skill 调用的辅助脚本，**无需安装 synth 包**，直接用 `python3` 运行：

| 子命令 | 功能 | 依赖 |
|--------|------|------|
| `graph-build [PATH]` | 从源码构建 `graphify-out/graph.json` | graphifyy |
| `graph-list [PATH]` | 列出代码图谱中检测到的模块 | 仅标准库 |
| `graph-query KEYWORD` | 按关键词搜索节点 | 仅标准库 |
| `card-data [PATH]` | 提取模块数据供 Claude 生成卡片 | 仅标准库 |

```bash
# 手动调用示例
python3 ~/.claude/skills/synth-card/synth_graph.py graph-build ~/my-repo
python3 ~/.claude/skills/synth-card/synth_graph.py graph-list  ~/my-repo
python3 ~/.claude/skills/synth-card/synth_graph.py card-data   ~/my-repo --feature auth
```

---

## 卸载

```bash
./install.sh --uninstall
```

---

## 工作原理

1. **graph-build** — 调用 `graphify` 的 Python API，对源码做 AST 提取，生成 `graphify-out/graph.json`（首次运行自动执行，后续复用缓存）
2. **graph-list** — 读取 `graph.json`，按 community 分组展示模块列表
3. **card-data** — 按关键词或 community ID 过滤节点和边，以 JSON 格式输出给 Claude
4. **Claude 生成卡片** — Claude 根据节点/边数据，按固定模板生成 Markdown 功能卡片
