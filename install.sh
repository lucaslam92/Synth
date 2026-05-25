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
# 检测是否为外部托管的 Python（Homebrew 等，需要 --break-system-packages）
# ---------------------------------------------------------------------------
PIP_FLAGS=""
EXTERNALLY_MANAGED=$("$PYTHON" -c "
import sysconfig, os
marker = os.path.join(sysconfig.get_path('stdlib'), 'EXTERNALLY-MANAGED')
print('yes' if os.path.exists(marker) else 'no')
")
if [ "$EXTERNALLY_MANAGED" = "yes" ]; then
    PIP_FLAGS="--break-system-packages"
    warn "检测到外部托管的 Python（如 Homebrew），将使用 --break-system-packages 安装"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# 升级 pip / setuptools
# ---------------------------------------------------------------------------
step "升级 pip / setuptools"

# shellcheck disable=SC2086
"$PYTHON" -m pip install --upgrade pip $PIP_FLAGS -q      && ok "pip 已升级"        || warn "pip 升级失败，继续使用当前版本"
# shellcheck disable=SC2086
"$PYTHON" -m pip install --upgrade setuptools $PIP_FLAGS -q && ok "setuptools 已升级" || warn "setuptools 升级失败，继续使用当前版本"

# ---------------------------------------------------------------------------
# 安装 Synth 核心依赖
# ---------------------------------------------------------------------------
step "安装 Synth 核心依赖"

# shellcheck disable=SC2086
"$PYTHON" -m pip install -e "$SCRIPT_DIR" $PIP_FLAGS -q
ok "Synth 核心依赖安装完成"

# ---------------------------------------------------------------------------
# 安装 graspologic（Leiden 社区检测，可选）
# ---------------------------------------------------------------------------
if [ "$LEIDEN" = true ]; then
    step "安装 graspologic（Leiden 社区检测）"
    echo "  graspologic 依赖 scipy / numpy / scikit-learn，首次安装可能需要几分钟..."

    # shellcheck disable=SC2086
    if "$PYTHON" -m pip install -e "$SCRIPT_DIR[leiden]" $PIP_FLAGS -q; then
        ok "graspologic 安装完成，Leiden 算法已启用"
    else
        warn "graspologic 安装失败，将回退到 Louvain 算法（功能不受影响）"
        warn "如需手动安装: $PYTHON -m pip install graspologic>=3.0 $PIP_FLAGS"
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

MODULES=("anthropic" "networkx" "typer" "rich")
for mod in "${MODULES[@]}"; do
    if "$PYTHON" -c "import $mod" 2>/dev/null; then
        ok "$mod"
    else
        err "$mod 导入失败"
        exit 1
    fi
done

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
# 只在 Key 未设置或为空时才提示
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  1. 设置 API Key（二选一）:"
    echo "       export ANTHROPIC_API_KEY=sk-ant-...   # 环境变量（推荐）"
    echo "       或在 synth.toml 中设置 [llm] api_key  # 写入配置文件"
    echo "       申请地址: https://console.anthropic.com/settings/keys"
    echo ""
    echo "  2. 创建配置文件:  synth init"
    echo "  3. 编辑配置:      \$EDITOR synth.toml"
    echo "  4. 运行合成:      synth run"
else
    ok "ANTHROPIC_API_KEY 已设置，无需额外配置"
    echo ""
    echo "  1. 创建配置文件:  synth init"
    echo "  2. 编辑配置:      \$EDITOR synth.toml"
    echo "  3. 运行合成:      synth run"
fi
echo ""
