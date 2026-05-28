#!/usr/bin/env bash
# install.sh — Install Synth skills (synth-card + feature-map) into Claude Code
#
# Usage:
#   ./install.sh              # install both skills
#   ./install.sh --no-dep     # skip pip install (graphifyy)
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
      echo "Installs two Claude Code skills:"
      echo "  /synth-card   — Generate feature cards for code modules"
      echo "  /feature-map  — Interactive HTML feature map + LLM JSON index"
      exit 0
      ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SYNTH_CARD_DEST="$CLAUDE_DIR/skills/synth-card"
FEATURE_MAP_DEST="$CLAUDE_DIR/skills/feature-map"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNTH_CARD_SRC="$SCRIPT_DIR/skills/synth-card"
FEATURE_MAP_SRC="$SCRIPT_DIR/skills/feature-map"

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if [[ "$UNINSTALL" == true ]]; then
  step "Uninstalling Synth skills"
  for dir in "$SYNTH_CARD_DEST" "$FEATURE_MAP_DEST"; do
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
# Verify source files
# ---------------------------------------------------------------------------
step "Checking source files"
errors=0
for f in "$SYNTH_CARD_SRC/SKILL.md" "$SYNTH_CARD_SRC/synth_graph.py" \
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
# Install Python dependencies
# feature-map auto-installs its heavy deps (tree-sitter family) on first run.
# We only pre-install graphifyy here, which is shared by both skills.
# ---------------------------------------------------------------------------
if [[ "$INSTALL_DEP" == true ]]; then
  step "Installing Python dependency: graphifyy"
  if command -v pip3 &>/dev/null; then
    PIP=pip3
  elif command -v pip &>/dev/null; then
    PIP=pip
  else
    warn "pip not found — skipping dependency install"
    warn "Please run: pip install graphifyy"
    PIP=""
  fi

  if [[ -n "$PIP" ]]; then
    if $PIP install --quiet graphifyy 2>/dev/null; then
      ok "graphifyy installed"
    elif $PIP install --quiet --break-system-packages graphifyy 2>/dev/null; then
      ok "graphifyy installed (Homebrew Python, used --break-system-packages)"
    else
      warn "graphifyy install failed — please run one of:"
      warn "  pip install graphifyy"
      warn "  pip install graphifyy --break-system-packages  # Homebrew Python"
      warn "  pip install graphifyy --user                   # user install"
    fi
  fi

  echo ""
  warn "Note: /feature-map also needs tree-sitter packages."
  warn "These are auto-installed the first time you run /feature-map."
  warn "Or pre-install manually:"
  warn "  pip install networkx tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}Installation complete!${RESET}"
echo ""
echo "Restart Claude Code, then:"
echo ""
echo "  /synth-card              — generate a feature card for a code module"
echo "  /synth-card auth         — card for anything matching 'auth'"
echo "  /synth-card --all        — batch generate cards for all modules"
echo ""
echo "  /feature-map             — analyze current directory"
echo "  /feature-map ./src       — analyze a subdirectory"
echo "  /feature-map /my/repo    — analyze a specific project"
