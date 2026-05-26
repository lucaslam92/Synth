#!/usr/bin/env bash
# install.sh — 安装 synth-card skill 到 Claude Code
#
# 用法:
#   ./install.sh            # 安装 skill（含依赖检查）
#   ./install.sh --no-dep   # 跳过 pip 依赖安装
#   ./install.sh --uninstall
#   ./install.sh --help

set -euo pipefail

# ---------------------------------------------------------------------------
# 颜色输出
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "${RED}✗${RESET}  $*" >&2; }
step() { echo -e "\n${BOLD}▶ $*${RESET}"; }

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
INSTALL_DEP=true
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --no-dep)     INSTALL_DEP=false ;;
    --uninstall)  UNINSTALL=true ;;
    --help|-h)
      echo "用法: ./install.sh [--no-dep] [--uninstall]"
      echo ""
      echo "  --no-dep     跳过 pip 依赖安装（graphifyy）"
      echo "  --uninstall  移除已安装的 skill"
      exit 0
      ;;
    *) err "未知参数: $arg"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# 确定 skill 安装目录
# ---------------------------------------------------------------------------
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILL_DIR="$CLAUDE_DIR/skills/synth-card"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/skills/synth-card"

# ---------------------------------------------------------------------------
# 卸载
# ---------------------------------------------------------------------------
if [[ "$UNINSTALL" == true ]]; then
  step "卸载 synth-card skill"
  if [[ -d "$SKILL_DIR" ]]; then
    rm -rf "$SKILL_DIR"
    ok "已移除 $SKILL_DIR"
  else
    warn "未找到已安装的 skill（$SKILL_DIR）"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# 检查源文件
# ---------------------------------------------------------------------------
step "检查源文件"
if [[ ! -f "$SRC_DIR/SKILL.md" ]] || [[ ! -f "$SRC_DIR/synth_graph.py" ]]; then
  err "找不到 skill 源文件，请在仓库根目录运行此脚本"
  err "  预期路径: $SRC_DIR"
  exit 1
fi
ok "源文件就绪: $SRC_DIR"

# ---------------------------------------------------------------------------
# 安装 skill 文件
# ---------------------------------------------------------------------------
step "安装 skill 到 $SKILL_DIR"
mkdir -p "$SKILL_DIR"
cp "$SRC_DIR/SKILL.md"        "$SKILL_DIR/SKILL.md"
cp "$SRC_DIR/synth_graph.py"  "$SKILL_DIR/synth_graph.py"
chmod +x "$SKILL_DIR/synth_graph.py"
ok "SKILL.md      → $SKILL_DIR/SKILL.md"
ok "synth_graph.py → $SKILL_DIR/synth_graph.py"

# ---------------------------------------------------------------------------
# 安装 Python 依赖（仅 graphifyy，用于 graph-build）
# ---------------------------------------------------------------------------
if [[ "$INSTALL_DEP" == true ]]; then
  step "安装 Python 依赖（graphifyy）"
  if command -v pip3 &>/dev/null; then
    PIP=pip3
  elif command -v pip &>/dev/null; then
    PIP=pip
  else
    warn "未找到 pip，跳过依赖安装"
    warn "请手动执行: pip install graphifyy"
    PIP=""
  fi

  if [[ -n "$PIP" ]]; then
    if $PIP install --quiet graphifyy 2>/dev/null; then
      ok "graphifyy 已安装"
    elif $PIP install --quiet --break-system-packages graphifyy 2>/dev/null; then
      ok "graphifyy 已安装（Homebrew Python，使用 --break-system-packages）"
    else
      warn "graphifyy 安装失败，请手动执行以下任一命令："
      warn "  pip install graphifyy"
      warn "  pip install graphifyy --break-system-packages  # Homebrew Python"
      warn "  pip install graphifyy --user                   # 用户目录安装"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}安装完成！${RESET}"
echo ""
echo "在 Claude Code 中输入 /synth-card 即可使用。"
echo ""
echo "示例："
echo "  /synth-card                  # 自动检测当前仓库，选择模块"
echo "  /synth-card auth             # 生成 auth 相关功能卡片"
echo "  /synth-card --all            # 批量生成所有模块卡片"
echo "  /synth-card ~/my-repo ingest # 指定仓库 + 功能关键词"
