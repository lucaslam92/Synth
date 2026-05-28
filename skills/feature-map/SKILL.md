---
name: feature-map
description: "Analyze any codebase and generate an interactive HTML feature map (functionality.html) and an LLM-navigable JSON index (FUNCTION_INDEX.json). Use when the user wants to explore a codebase visually, understand module boundaries and entry points, trace call chains, or create a structured function index for fast LLM-assisted code navigation. Trigger: /feature-map"
trigger: /feature-map
---

# /feature-map

Analyze a codebase and produce two artifacts:

- **functionality.html** — Interactive browser feature map: every function, class, entry point, and call chain
- **FUNCTION_INDEX.json** — Structured index that lets an LLM locate any function in O(1) without grep or scanning

## Usage

```
/feature-map                     # analyze current directory
/feature-map ./src               # analyze a subdirectory
/feature-map /path/to/repo       # analyze a specific project
/feature-map . --no-html         # JSON index only
/feature-map . --no-json         # HTML only
/feature-map . -o ./my-output    # custom output directory
```

---

## Steps

### 1. Resolve the target path

Use the path given after `/feature-map`, defaulting to `.`. Resolve relative paths from the current working directory.

### 2. Locate the script

```bash
SCRIPT="${ CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/feature-map/feature_map.py"
```

If not found there, check `./feature_map.py` in the current directory (fallback for running directly from the Synth repo).

If neither location has the script, tell the user to install the skill:
```
./install.sh   (from the Synth repo root)
```
Stop.

### 3. Run the analysis

Output goes to `./feature-map-out/` in the **current working directory** — not inside the target repo.

```bash
python3 "$SCRIPT" "$TARGET_PATH"
```

With options:
```bash
python3 "$SCRIPT" "$TARGET_PATH" [-o <output_dir>] [--no-html] [--no-json]
```

The script will auto-install any missing Python packages (graphifyy, networkx, tree-sitter family) the first time it runs, printing what it's installing before it starts.

If the analysis takes more than 30 seconds, reassure the user that large codebases take time.

### 4. Read the summary

The script prints a single JSON line to stdout on success:

```json
{"features": 12, "functions": 340, "output_dir": "/abs/path/to/out", "html_path": "...", "json_path": "..."}
```

Parse this for the exact output paths and counts.

### 5. Report to the user

Tell the user:
- How many feature modules and functions were found
- The path to `functionality.html` — suggest opening in a browser
- The path to `FUNCTION_INDEX.json` — explain it enables O(1) LLM code navigation
- Offer to explain any feature or trace a specific call chain

---

## What the outputs are for

**functionality.html** — Open in any browser. The left sidebar lists all detected feature modules. Click a module to see its entry points, call chain diagram (rendered as a graph), and complete function table. Use the search box to filter by function name, file, or feature.

**FUNCTION_INDEX.json** — Feed this file to Claude (or any LLM) along with a question like "find where payments are processed". The LLM looks up `features["payments/..."]`, gets the `entry_point_ids`, then looks up `functions[id]` to find the exact `file_path:line_start–line_end` without scanning the whole codebase.

---

## Error reference

| Situation | Action |
|-----------|--------|
| Script not found | Tell user to run `./install.sh`, stop |
| Missing Python packages | Script installs them automatically; if that fails, tell user to run `pip install graphifyy networkx tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript` |
| No supported source files | Tell user — supported languages: Python, JS/TS, Go, Rust, Java, C/C++, Ruby, C#, Kotlin, Scala |
| Script fails mid-run | Show the stderr output to the user; suggest the manual pip install command above |
| Large codebase (>30 s) | Reassure the user and let it continue |
