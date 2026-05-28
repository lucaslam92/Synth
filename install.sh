#!/usr/bin/env bash
# install.sh — Install Synth skills (synth-index + synth-card + feature-map) into Claude Code
#
# Usage:
#   ./install.sh              # install all three skills
#   ./install.sh --no-dep     # skip pip install (graphifyy + tree-sitter)
#   ./install.sh --uninstall  # remove installed skills
#   ./install.sh --help

set -euo pipefail

# ---------------------------------------------------------------------------
# Color output
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
# Argument parsing
# ---------------------------------------------------------------------------
INSTALL_DEP=true
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --no-dep)     INSTALL_DEP=false ;;
    --uninstall)  UNINSTALL=true ;;
    --help|-h)
      echo "Usage: ./install.sh [--no-dep] [--uninstall]"
      echo ""
      echo "  --no-dep     Skip pip install (graphifyy and tree-sitter packages)"
      echo "  --uninstall  Remove installed skills"
      echo ""
      echo "Installs three Claude Code skills:"
      echo "  /synth-index  — Build FUNCTION_INDEX.json for a codebase"
      echo "  /synth-card   — Generate feature cards for code modules"
      echo "  /feature-map  — Interactive HTML feature map"
      exit 0
      ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SYNTH_INDEX_DEST="$CLAUDE_DIR/skills/synth-index"
SYNTH_CARD_DEST="$CLAUDE_DIR/skills/synth-card"
FEATURE_MAP_DEST="$CLAUDE_DIR/skills/feature-map"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNTH_INDEX_SRC="$SCRIPT_DIR/skills/synth-index"
SYNTH_CARD_SRC="$SCRIPT_DIR/skills/synth-card"
FEATURE_MAP_SRC="$SCRIPT_DIR/skills/feature-map"

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if [[ "$UNINSTALL" == true ]]; then
  step "Uninstalling Synth skills"
  for dir in "$SYNTH_INDEX_DEST" "$SYNTH_CARD_DEST" "$FEATURE_MAP_DEST"; do
    if [[ -d "$dir" ]]; then
      rm -rf "$dir"
      ok "Removed $dir"
    else
      warn "Not found: $dir"
    fi
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# Verify Python 3.8+
# ---------------------------------------------------------------------------
step "Checking Python version"
if ! command -v python3 &>/dev/null; then
  err "python3 not found — please install Python 3.8 or later"
  exit 1
fi
if ! python3 -c "import sys; assert sys.version_info >= (3,8), 'too old'" 2>/dev/null; then
  err "Python 3.8+ required (found: $(python3 --version 2>&1))"
  exit 1
fi
ok "$(python3 --version)"

# ---------------------------------------------------------------------------
# Verify source files
# ---------------------------------------------------------------------------
step "Checking source files"
errors=0
for f in "$SYNTH_INDEX_SRC/SKILL.md" "$SYNTH_INDEX_SRC/synth_index.py" \
          "$SYNTH_CARD_SRC/SKILL.md"  "$SYNTH_CARD_SRC/synth_graph.py"  \
          "$FEATURE_MAP_SRC/SKILL.md" "$FEATURE_MAP_SRC/feature_map.py"; do
  if [[ ! -f "$f" ]]; then
    err "Missing: $f"
    errors=$((errors + 1))
  fi
done
if [[ $errors -gt 0 ]]; then
  err "Run this script from the Synth repo root directory."
  exit 1
fi
ok "Source files ready"

# ---------------------------------------------------------------------------
# Install synth-index
# ---------------------------------------------------------------------------
step "Installing synth-index → $SYNTH_INDEX_DEST"
mkdir -p "$SYNTH_INDEX_DEST"
cp "$SYNTH_INDEX_SRC/SKILL.md"       "$SYNTH_INDEX_DEST/SKILL.md"
cp "$SYNTH_INDEX_SRC/synth_index.py" "$SYNTH_INDEX_DEST/synth_index.py"
[ -f "$SYNTH_INDEX_SRC/requirements.txt" ] && \
  cp "$SYNTH_INDEX_SRC/requirements.txt" "$SYNTH_INDEX_DEST/requirements.txt"
chmod +x "$SYNTH_INDEX_DEST/synth_index.py"
ok "SKILL.md       → $SYNTH_INDEX_DEST/SKILL.md"
ok "synth_index.py → $SYNTH_INDEX_DEST/synth_index.py"

# ---------------------------------------------------------------------------
# Install synth-card
# ---------------------------------------------------------------------------
step "Installing synth-card → $SYNTH_CARD_DEST"
mkdir -p "$SYNTH_CARD_DEST"
cp "$SYNTH_CARD_SRC/SKILL.md"        "$SYNTH_CARD_DEST/SKILL.md"
cp "$SYNTH_CARD_SRC/synth_graph.py"  "$SYNTH_CARD_DEST/synth_graph.py"
chmod +x "$SYNTH_CARD_DEST/synth_graph.py"
ok "SKILL.md       → $SYNTH_CARD_DEST/SKILL.md"
ok "synth_graph.py → $SYNTH_CARD_DEST/synth_graph.py"

# ---------------------------------------------------------------------------
# Install feature-map
# ---------------------------------------------------------------------------
step "Installing feature-map → $FEATURE_MAP_DEST"
mkdir -p "$FEATURE_MAP_DEST"
cp "$FEATURE_MAP_SRC/SKILL.md"       "$FEATURE_MAP_DEST/SKILL.md"
cp "$FEATURE_MAP_SRC/feature_map.py" "$FEATURE_MAP_DEST/feature_map.py"
chmod +x "$FEATURE_MAP_DEST/feature_map.py"
ok "SKILL.md       → $FEATURE_MAP_DEST/SKILL.md"
ok "feature_map.py → $FEATURE_MAP_DEST/feature_map.py"

# ---------------------------------------------------------------------------
# Install Python dependencies for synth-index
# /synth-card and /feature-map only need stdlib Python — no deps to install.
# /synth-index needs graphifyy + networkx + tree-sitter (auto-installs on first run;
# we pre-install here for a faster first /synth-index run).
# ---------------------------------------------------------------------------
if [[ "$INSTALL_DEP" == true ]]; then
  step "Installing Python dependencies for /synth-index"
  if command -v pip3 &>/dev/null; then
    PIP=pip3
  elif command -v pip &>/dev/null; then
    PIP=pip
  else
    warn "pip not found — skipping dependency install"
    warn "Please run: pip install graphifyy networkx tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript"
    PIP=""
  fi

  if [[ -n "$PIP" ]]; then
    REQS="$SYNTH_INDEX_DEST/requirements.txt"
    if [[ -f "$REQS" ]]; then
      if $PIP install --quiet -r "$REQS" 2>/dev/null; then
        ok "Dependencies installed from requirements.txt"
      elif $PIP install --quiet --break-system-packages -r "$REQS" 2>/dev/null; then
        ok "Dependencies installed (Homebrew Python, used --break-system-packages)"
      else
        warn "Dependency install failed — please run one of:"
        warn "  pip install -r $REQS"
        warn "  pip install -r $REQS --break-system-packages  # Homebrew Python"
        warn "  pip install -r $REQS --user                   # user install"
      fi
    else
      # Fallback: install individually
      PKGS="graphifyy networkx tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript"
      if $PIP install --quiet $PKGS 2>/dev/null; then
        ok "Dependencies installed"
      elif $PIP install --quiet --break-system-packages $PKGS 2>/dev/null; then
        ok "Dependencies installed (Homebrew Python, used --break-system-packages)"
      else
        warn "Dependency install failed — please run: pip install $PKGS"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}Installation complete!${RESET}"
echo ""
echo "Restart Claude Code, then use the three skills together:"
echo ""
echo "  /synth-index             — build code index for current directory"
echo "  /synth-index /my/repo    — build code index for a specific repo"
echo "  /synth-index . --force   — force rebuild after code changes"
echo ""
echo "  /feature-map             — render interactive HTML feature map"
echo "  /feature-map ./src       — render HTML for a subdirectory"
echo ""
echo "  /synth-card              — generate a feature card for a code module"
echo "  /synth-card auth         — card for anything matching 'auth'"
echo "  /synth-card --all        — batch generate cards for all modules"
echo ""
echo "Typical workflow:"
echo "  /synth-index → /feature-map   (explore visually)"
echo "  /synth-index → /synth-card    (generate feature cards)"
