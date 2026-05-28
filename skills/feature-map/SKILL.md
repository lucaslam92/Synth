---
name: feature-map
description: "Generate an interactive HTML feature map (functionality.html) from a code index produced by /synth-index. Requires FUNCTION_INDEX.json to already exist. Use when the user wants to explore a codebase visually, understand module boundaries, entry points, and call chains. Trigger: /feature-map"
trigger: /feature-map
---

# /feature-map

Render an **interactive HTML feature map** from a code index.

- **functionality.html** — Browser visualization: every function, class, entry point, and call chain, grouped by feature module

> **Requires a code index.** Run `/synth-index [path]` first if `FUNCTION_INDEX.json` doesn't exist yet.

## Usage

```
/feature-map                     # render HTML for current directory
/feature-map /path/to/repo       # render HTML for a specific repo
/feature-map . -o ./my-output    # custom output directory
/feature-map . --index /path/to/FUNCTION_INDEX.json  # explicit index path
```

---

## Parse arguments

| Token | Variable | Default |
|-------|----------|---------|
| `-o <dir>` | `OUT_DIR` | `""` (defaults to `./feature-map-out`) |
| `--index <path>` | `INDEX_PATH` | `""` |
| First path token | `REPO_PATH` | `.` |

---

## Step 0 — Locate the skill script

```bash
SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/feature-map"
FEATURE_MAP="$SKILL_DIR/feature_map.py"
```

If `feature_map.py` is missing, tell the user and stop:

```
feature_map.py not found at $SKILL_DIR

To install:
  ./install.sh    # from the Synth repo root
```

---

## Step 1 — Run the renderer

```bash
OUT_FLAG=""
[ -n "$OUT_DIR" ] && OUT_FLAG="-o $OUT_DIR"

INDEX_FLAG=""
[ -n "$INDEX_PATH" ] && INDEX_FLAG="--index $INDEX_PATH"

RESULT=$(python3 "$FEATURE_MAP" "$REPO_PATH" $OUT_FLAG $INDEX_FLAG)
EXIT_CODE=$?
```

Parse the JSON from stdout on success:

| Field | Meaning |
|-------|---------|
| `status` | `"ok"` |
| `html_path` | Absolute path to the generated `functionality.html` |
| `features` | Number of feature modules in the map |
| `functions` | Number of functions indexed |

---

## Step 2 — Report to user

On success:

```
✅ Feature map generated

  📄 {html_path}

  {features} feature modules · {functions} functions

Open functionality.html in any browser to explore the map.
```

---

## Error reference

| Situation | Action |
|-----------|--------|
| `feature_map.py` not found | Show install command, stop |
| No `FUNCTION_INDEX.json` found | Tell user: run `/synth-index {REPO_PATH}` first, then retry `/feature-map` |
| Path does not exist | Ask user to check the path |
| Script fails | Show stderr output |
