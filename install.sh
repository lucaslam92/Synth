#!/usr/bin/env bash
# install.sh — Synth 安装脚本
#
# 用法:
#   ./install.sh              # 在 .venv/ 中安装（含 Leiden 社区检测）
#   ./install.sh --no-leiden  # 仅安装核心依赖，跳过 graspologic
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
LEIDEN=true

for arg in "$@"; do
    case "$arg" in
        --no-leiden) LEIDEN=false ;;
        --help|-h)
            echo "用法: ./install.sh [--no-leiden]"
            echo ""
            echo "选项:"
            echo "  --no-leiden   跳过 graspologic 安装（不支持 Leiden 社区检测，回退到 Louvain）"
            echo "  --help        显示此帮助"
            exit 0
            ;;
        *)
            err "未知参数: $arg"
            echo "运行 ./install.sh --help 查看用法"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# 检查 Python 版本（需要 >= 3.10）
# ---------------------------------------------------------------------------
step "检查 Python 版本"

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            ok "找到 $cmd $ver"
            break
        else
            warn "$cmd 版本为 $ver，需要 >= 3.10，跳过"
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "未找到 Python 3.10+，请先安装: https://www.python.org/downloads/"
    err "macOS 用户可运行: brew install python@3.13"
    exit 1
fi

# ---------------------------------------------------------------------------
# 创建虚拟环境
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

step "创建虚拟环境 (.venv/)"

if [ -d "$VENV_DIR" ]; then
    warn ".venv/ 已存在，复用现有虚拟环境"
    warn "如需全新安装，请先删除: rm -rf .venv/"
else
    "$PYTHON" -m venv "$VENV_DIR"
    ok "虚拟环境已创建: $VENV_DIR"
fi

# 后续所有操作都使用 venv 内的 Python / pip
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ---------------------------------------------------------------------------
# 升级 pip / setuptools
# ---------------------------------------------------------------------------
step "升级 pip / setuptools"

"$PIP" install --upgrade pip -q      && ok "pip 已升级"       || warn "pip 升级失败，继续使用当前版本"
"$PIP" install --upgrade setuptools -q && ok "setuptools 已升级" || warn "setuptools 升级失败，继续使用当前版本"

# ---------------------------------------------------------------------------
# 安装 Synth 核心依赖
# ---------------------------------------------------------------------------
step "安装 Synth 核心依赖"

"$PIP" install -e "$SCRIPT_DIR" -q
ok "Synth 核心依赖安装完成"

# ---------------------------------------------------------------------------
# 安装 graspologic（Leiden 社区检测，可选）
# ---------------------------------------------------------------------------
if [ "$LEIDEN" = true ]; then
    step "安装 graspologic（Leiden 社区检测）"
    echo "  graspologic 依赖 scipy / numpy / scikit-learn，首次安装可能需要几分钟..."

    if "$PIP" install -e "$SCRIPT_DIR[leiden]" -q; then
        ok "graspologic 安装完成，Leiden 算法已启用"
    else
        warn "graspologic 安装失败，将回退到 Louvain 算法（功能不受影响）"
        warn "如需手动安装: $PIP install graspologic>=3.0"
    fi
else
    warn "已跳过 graspologic 安装（--no-leiden），社区检测将使用 Louvain 算法"
fi

# ---------------------------------------------------------------------------
# 验证安装
# ---------------------------------------------------------------------------
step "验证安装"

if ! "$PY" -m synth --help &>/dev/null; then
    err "synth CLI 验证失败，请检查上方错误信息"
    exit 1
fi
ok "synth CLI 可用"

MODULES=("anthropic" "networkx" "typer" "rich")
for mod in "${MODULES[@]}"; do
    if "$PY" -c "import $mod" 2>/dev/null; then
        ok "$mod"
    else
        err "$mod 导入失败"
        exit 1
    fi
done

if "$PY" -c "from graspologic.partition import leiden" 2>/dev/null; then
    ok "graspologic (leiden) ✓ — 将使用 Leiden 社区检测算法"
else
    warn "graspologic 不可用 — 将回退到 Louvain 算法"
fi

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}✓ 安装完成！${RESET}"
echo ""
echo "激活虚拟环境："
echo "  source .venv/bin/activate"
echo ""
echo "或直接使用 venv 内的命令（无需激活）："
echo "  .venv/bin/synth --help"
echo ""
echo "下一步："
echo "  1. 设置 API Key:  export ANTHROPIC_API_KEY=sk-..."
echo "  2. 创建配置文件:  synth init"
echo "  3. 编辑配置:      \$EDITOR synth.toml"
echo "  4. 运行合成:      synth run"
echo ""
