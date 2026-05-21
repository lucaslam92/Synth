#!/usr/bin/env bash
# install.sh — Synth 安装脚本
#
# 用法:
#   ./install.sh              # 安装全部依赖（含 Leiden 社区检测）
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
for cmd in python3 python; do
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
    exit 1
fi

# ---------------------------------------------------------------------------
# 检查 pip
# ---------------------------------------------------------------------------
step "检查 pip"

if ! "$PYTHON" -m pip --version &>/dev/null; then
    err "pip 不可用，请先安装: $PYTHON -m ensurepip"
    exit 1
fi

ok "pip 可用: $($PYTHON -m pip --version)"

# ---------------------------------------------------------------------------
# 升级 pip 和 setuptools
# ---------------------------------------------------------------------------
step "升级 pip / setuptools"

# 逐个升级：wheel 在部分系统（Debian/Ubuntu）由系统包管理器管理，跳过即可
"$PYTHON" -m pip install --upgrade pip -q && ok "pip 已升级" || warn "pip 升级失败，继续使用当前版本"
"$PYTHON" -m pip install --upgrade setuptools -q && ok "setuptools 已升级" || warn "setuptools 升级失败，继续使用当前版本"

# ---------------------------------------------------------------------------
# 安装 Synth
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step "安装 Synth 核心依赖"

"$PYTHON" -m pip install -e "$SCRIPT_DIR" -q
ok "Synth 核心依赖安装完成"

# ---------------------------------------------------------------------------
# 安装 graspologic（Leiden 社区检测）
# ---------------------------------------------------------------------------
if [ "$LEIDEN" = true ]; then
    step "安装 graspologic（Leiden 社区检测）"
    echo "  graspologic 依赖 scipy / numpy / scikit-learn，首次安装可能需要几分钟..."

    if "$PYTHON" -m pip install -e "$SCRIPT_DIR[leiden]" -q; then
        ok "graspologic 安装完成，Leiden 算法已启用"
    else
        warn "graspologic 安装失败，将回退到 Louvain 算法（功能不受影响）"
        warn "如需手动安装: pip install graspologic>=3.0"
    fi
else
    warn "已跳过 graspologic 安装（--no-leiden），社区检测将使用 Louvain 算法"
fi

# ---------------------------------------------------------------------------
# 验证安装
# ---------------------------------------------------------------------------
step "验证安装"

if ! "$PYTHON" -m synth --help &>/dev/null; then
    err "synth CLI 验证失败，请检查上方错误信息"
    exit 1
fi

ok "synth CLI 可用"

# 检查各核心模块是否可导入
MODULES=("anthropic" "networkx" "typer" "rich")
for mod in "${MODULES[@]}"; do
    if "$PYTHON" -c "import $mod" 2>/dev/null; then
        ok "$mod"
    else
        err "$mod 导入失败"
        exit 1
    fi
done

# 检查 Leiden（可选）
if "$PYTHON" -c "from graspologic.partition import leiden" 2>/dev/null; then
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
echo "下一步："
echo "  1. 设置 API Key:  export ANTHROPIC_API_KEY=sk-..."
echo "  2. 创建配置文件:  synth init"
echo "  3. 编辑配置:      \$EDITOR synth.toml"
echo "  4. 运行合成:      synth run"
echo ""
