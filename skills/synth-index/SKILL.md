---
name: synth-index
description: "Build a structured code index (FUNCTION_INDEX.json) for a codebase. Runs graphify graph construction + tree-sitter AST enrichment. Must be run before /feature-map or /synth-card. Trigger: /synth-index"
trigger: /synth-index
---

# /synth-index

Build a **code index** for any codebase. Produces `FUNCTION_INDEX.json` — a structured,
LLM-ready map of features, functions, data models, and call chains.

Other skills (`/feature-map`, `/synth-card`) consume this index. Run `/synth-index` once
per repo, then re-run with `--force` after significant code changes.

## Usage

```
/synth-index                     # analyze current directory
/synth-index /path/to/repo       # analyze specific directory
/synth-index . -o ./my-analysis  # custom output directory
/synth-index . --force           # force rebuild
```

---

## Parse arguments

| Token | Variable | Default |
|-------|----------|---------|
| `--force` / `-f` | `FORCE=true` | `false` |
| `-o <dir>` | `OUT_DIR` | `""` (defaults to `{repo_root}/synth-out/`) |
| First path token | `REPO_PATH` | `.` |

---

## Step 0 — Locate the skill script

```bash
SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/synth-index"
SYNTH_INDEX="$SKILL_DIR/synth_index.py"
```

If `synth_index.py` is missing, tell the user and stop:

```
synth_index.py not found at $SKILL_DIR

To install:
  ./install.sh    # from the Synth repo root
```

---

## Step 1 — Run the indexer

```bash
FORCE_FLAG=""
[ "$FORCE" = "true" ] && FORCE_FLAG="--force"

OUT_FLAG=""
[ -n "$OUT_DIR" ] && OUT_FLAG="-o $OUT_DIR"

RESULT=$(python3 "$SYNTH_INDEX" "$REPO_PATH" $FORCE_FLAG $OUT_FLAG)
```

Parse the JSON from stdout:

| Field | Meaning |
|-------|---------|
| `status` | `"ok"` (just built) or `"exists"` (already up to date) |
| `repo_root` | Absolute path to the repo that was analyzed |
| `output_dir` | Absolute path to the output directory |
| `index_path` | Absolute path to the generated FUNCTION_INDEX.json |
| `features` | Number of feature modules detected |
| `functions` | Number of functions indexed |
| `data_models` | Number of data models (dataclasses, schemas, interfaces) |
| `generated_at` | ISO 8601 timestamp |

---

## Step 2 — Report to user

On success:

```
✅ Code index built for {repo_name}

  📋 {index_path}

  {features} feature modules · {functions} functions · {data_models} data models
  Generated: {generated_at}

Next steps:
  /feature-map {repo_path}              — interactive HTML visualization
  /synth-card  {repo_path}              — generate feature cards (Markdown)
  /feature-map . -o ./out               — custom output directory
  /synth-index . --force                — rebuild after code changes
```

If `status` is `"exists"`, add:
> (Index already up to date — pass `--force` to rebuild)

---

## Error reference

| Situation | Action |
|-----------|--------|
| `synth_index.py` not found | Show install command, stop |
| `graphifyy` not installed | Tell user: `pip install graphifyy`, stop |
| Path does not exist | Ask user to check the path |
| No supported source files found | List supported languages (.py .ts .js .go .rs .java …), stop |
| Build fails | Show stderr output, suggest `pip install graphifyy` |
