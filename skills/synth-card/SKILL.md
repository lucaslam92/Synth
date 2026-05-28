---
name: synth-card
description: "Generate structured feature cards from a codebase. Use when the user wants to understand what a module/feature does, explore a repo's functionality, or produce shareable feature cards. Trigger: /synth-card"
trigger: /synth-card
---

# /synth-card

Generate structured **feature cards** — a concise, readable summary of what a code module does, its key components, and how they call each other.

## Usage

```
/synth-card                      # detect current repo, ask which module
/synth-card auth                 # card for anything matching "auth"
/synth-card user login flow      # card for user login related code
/synth-card --all                # generate cards for every detected module
/synth-card <path>               # run on a specific directory
/synth-card <path> <feature>     # specific path + keyword
/synth-card --lang en            # force English output
/synth-card --rebuild            # force-rebuild the code graph
/synth-card -o ./my-cards        # custom output dir (batch mode)
```

---

## Parse arguments

From the text after `/synth-card`, extract these flags and tokens:

| Token | Variable | Default |
|-------|----------|---------|
| `--help` / `-h` | — | Print usage and stop |
| `--all` | `BATCH=true` | `false` |
| `--lang en` or `--lang zh` | `LANG` | `auto` (infer from user's message language) |
| `--rebuild` | `REBUILD=true` | `false` |
| `-o <dir>` | `OUT_DIR` | `synth-out/cards` |
| First token starting with `.` `/` `~` or containing `/` | `REPO_PATH` | `.` |
| Everything else | `FEATURE_QUERY` | `""` |

---

## Step 0 — Locate the skill script

```bash
SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/synth-card"
SYNTH_GRAPH="$SKILL_DIR/synth_graph.py"
```

If `synth_graph.py` is missing, tell the user and stop:

```
synth_graph.py not found at $SKILL_DIR

To install:
  ./install.sh          # from the Synth repo root
  # or:
  mkdir -p $SKILL_DIR && cp synth_graph.py $SKILL_DIR/
```

---

## Step 1 — Locate the repository root

```bash
ROOT_JSON=$(python3 "$SYNTH_GRAPH" graph-root "$REPO_PATH")
```

Parse the JSON. Fields:

| Field | Meaning |
|-------|---------|
| `repo_root` | Absolute path — use for all subsequent commands |
| `repo_name` | Human-readable name for card header |
| `has_graph` | Whether `graphify-out/graph.json` already exists |
| `graph_mtime` | Unix timestamp of the graph (null if no graph) |
| `has_source` | Whether supported source files exist |

If `has_source` is false, tell the user no supported source files were found (Python, JS/TS, Go, Rust, Java) and stop.

If `has_graph` is true and `graph_mtime` is more than 24 hours old:
> ⚠️ Code graph was built N days ago — run `/synth-card --rebuild` if the codebase has changed since then.

---

## Step 2 — Build the code graph (if needed)

Skip this step if `has_graph` is true AND `--rebuild` was not passed.

If building, tell the user first: "Analyzing code structure — first run takes a moment…"

```bash
# Without --rebuild:
python3 "$SYNTH_GRAPH" graph-build "$REPO_ROOT"
# With --rebuild:
python3 "$SYNTH_GRAPH" graph-build "$REPO_ROOT" --force
```

If the command fails with an import error, tell the user:
```
Run: pip install graphifyy
```
Then stop.

---

## Step 3 — List detected modules

```bash
MODULE_JSON=$(python3 "$SYNTH_GRAPH" graph-list "$REPO_ROOT" --json)
```

Parse the JSON array. Each element has: `community_id`, `label`, `size`, `files`, `sample_nodes`.

---

## Step 4 — Determine scope

### A — Feature query provided

```bash
DATA_JSON=$(python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --feature "$FEATURE_QUERY")
```

Check `action` in the response:
- `"generate_card"` → proceed to Step 5
- `"no_match"` → tell the user, display the module list from `MODULE_JSON`, ask which module to use

### B — No query (interactive)

Display the module list from `MODULE_JSON` as a numbered table. Ask:

> Which module would you like a feature card for? Enter a number, name, or "all".

On reply:
- Number or name → resolve to `community_id`, then:
  ```bash
  DATA_JSON=$(python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --module <community_id>)
  ```
- "all" → switch to batch mode (same as `--all`)

### C — Batch mode (`--all` or user chose "all")

For each `community_id` in `MODULE_JSON`:
```bash
DATA_JSON=$(python3 "$SYNTH_GRAPH" card-data "$REPO_ROOT" --module <community_id>)
```
Generate a card (Step 5) for each. Save to `$OUT_DIR/<label>.md`.
After all done, print:
```
✓ Generated N feature cards → $OUT_DIR/
  → $OUT_DIR/auth.md
  → $OUT_DIR/orders.md
  ...
```

---

## Step 5 — Generate the feature card

Using the JSON from `card-data` (where `action` is `"generate_card"`), write a card in this exact format:

```markdown
## Feature Card: {label}

| Field | Value |
|-------|-------|
| Repo | {repo} |
| Primary path | {most common parent directory among nodes' source_file values} |
| Components | {node_count} |

### What it does

{One paragraph for a developer new to this codebase. State concretely what the module does,
the key data flow, and any important design patterns or algorithms. Name the key
classes/functions. Under 200 words.}

### Key components

{Bullet list — one line per important class/function, one sentence on its role.}

### Internal call relationships

{Based on `edges`, describe how the main components call each other.
If edges is empty, write: "No call relationship data available."}

### External dependencies

{If source_file paths or node labels reveal cross-module imports, list them.
Omit this section if nothing is apparent.}
```

**Language:** Use the language set by `--lang`. When `--lang auto`, match the language the user wrote their `/synth-card` command in.

Rules:
- Only use data from `nodes` and `edges` — do not invent functionality
- Each card must be self-contained — no "as described above" references
- Specific > vague: name actual functions and classes rather than describing them generically

---

## Step 6 — Output

**Single card** → print Markdown directly in the conversation.

**Batch mode** → write each card to `$OUT_DIR/<label>.md`, then print the summary.

---

## Error reference

| Situation | Action |
|-----------|--------|
| `synth_graph.py` not installed | Show install command, stop |
| `graphifyy` not installed | Tell user to run `pip install graphifyy`, stop |
| Path does not exist | Ask user to check the path |
| No supported source files | List supported languages, stop |
| `graph-build` fails | Show error, suggest `pip install graphifyy`, stop |
| Keyword has no match | Show module list from `MODULE_JSON`, ask user to choose |
| Graph is stale (>24 h) | Warn with `--rebuild` suggestion (do not block — proceed) |
