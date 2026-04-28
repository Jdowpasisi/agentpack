# AgentPack

**Pre-built repo context for non-agentic Claude workflows.**

AgentPack is most useful when Claude has no tool access — piped CLI sessions, API calls, CI pipelines, PR reviews. It scans your repo once, builds an offline summary cache of every file, then on each task packs only the relevant files into a tight context document you pipe straight into Claude.

```bash
agentpack pack --agent claude --task "fix auth session bug" --print | claude
```

If you're using **Claude Code** (interactive, with tool access), Claude already reads files on demand — agentpack adds less value there. The sweet spot is everywhere else.

---

## When it helps

| Workflow | Value |
|---|---|
| `agentpack pack --print \| claude` — piped, no tools | **High** — Claude has no file access; pack is its only context |
| `claude < .agentpack/context.claude.md` — stdin | **High** — same |
| Claude API calls without tool use | **High** — same |
| CI: generate pack per PR, attach as artifact | **High** — reviewers get instant task context |
| Large repos (>50k tokens) where exploration is slow | **Medium** — summary cache eliminates repeated file reads |
| Claude Code interactive session | **Low** — Claude reads files on demand already |

---

## Install

```bash
pip install agentpack
```

Requires Python 3.10+.

---

## Quickstart

```bash
cd your-project/
agentpack init
agentpack summarize              # build offline summary cache once
agentpack pack --agent claude --task "fix auth session bug" --print | claude
```

Or save to file and pipe later:

```bash
agentpack pack --agent claude --task "fix auth session bug"
claude < .agentpack/context.claude.md
```

---

## The summary cache — the core feature

Run once, reuse forever:

```bash
agentpack summarize
```

This builds an offline summary of every file in your repo — no API calls, no network. Each summary captures:
- What the file does and its responsibility
- Exported classes, functions, and their signatures with extracted bodies
- Import dependencies

Summaries are stored in `.agentpack/cache/` keyed by file hash. When a file changes, only that file's summary is rebuilt on the next pack. When nothing changes, `agentpack pack` takes milliseconds.

**Team tip:** commit the cache so every developer and CI job gets summaries for free:

```bash
agentpack init --share-cache    # removes cache/ from .gitignore
git add .agentpack/cache/
git commit -m "chore: add agentpack summary cache"
```

Now `agentpack pack` runs in under 100ms for every teammate — no per-machine summarize step.

---

## Honest token framing

AgentPack's pack is typically 10,000–25,000 tokens. Comparing that to "raw repo size" (200k–2M tokens) is misleading — nobody dumps the whole repo into Claude.

The real comparison for a piped/API workflow is: **what would you have to manually copy-paste** to give Claude enough context to work? For a typical bug fix that touches 3 files with 10 relevant dependencies, that's roughly 30,000–80,000 tokens assembled by hand. AgentPack gets you there in one command.

For agentic workflows (Claude Code), the comparison is tool calls: reading 15 files via tool calls costs ~2,000 tokens in tool scaffolding overhead. The pack costs ~1,500 tokens of metadata. Roughly equivalent — neither is clearly cheaper there.

---

## CI/CD: pack per PR

Add to `.github/workflows/agentpack.yml`:

```yaml
name: AgentPack context

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  pack:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install agentpack

      - name: Generate context pack
        run: |
          agentpack init --yes
          agentpack pack --agent claude \
            --task "${{ github.event.pull_request.title }}" \
            --since origin/${{ github.base_ref }} \
            --mode balanced

      - name: Upload context pack
        uses: actions/upload-artifact@v4
        with:
          name: agentpack-context
          path: .agentpack/context.claude.md
          retention-days: 7
```

Reviewers download the artifact and run:

```bash
claude < context.claude.md
```

No repo clone needed. Claude gets focused context for exactly the PR's changes.

---

## Commands

### `agentpack init`

Initialize AgentPack in the current directory.

```bash
agentpack init                  # interactive mode picker
agentpack init --yes            # non-interactive, use defaults (good for CI)
agentpack init --share-cache    # commit cache/ to git for team sharing
```

Creates:
```
.agentignore              # gitignore-style file exclusion rules
.agentpack/
  config.toml             # configuration (safe to commit)
  .gitignore              # excludes cache/, snapshots/, context.* by default
  cache/                  # offline summary cache
  snapshots/              # file hash snapshots
```

---

### `agentpack summarize`

Build or refresh the offline summary cache. **No API calls.**

```bash
agentpack summarize              # build summaries for all files not yet cached
agentpack summarize --refresh    # force rebuild all
```

Run this once after `init`. After that, pack automatically rebuilds summaries only for changed files.

---

### `agentpack pack`

Generate a context pack.

```bash
# Pipe directly into Claude (primary workflow)
agentpack pack --agent claude --task "fix auth session bug" --print | claude

# Save to file
agentpack pack --agent claude --task "fix auth session bug"
claude < .agentpack/context.claude.md

# Only include changes since a git ref
agentpack pack --agent claude --task "review these changes" --since main

# Watch mode — re-packs on every file change
agentpack pack --agent claude --task "refactor auth" --session
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--agent` | `claude` | Target agent (`claude` or `generic`) |
| `--task` | `auto` | Task description, or `auto` to infer from git |
| `--mode` | `balanced` | Budget mode: `minimal`, `balanced`, `deep` |
| `--budget` | 25000 | Token budget |
| `--since` | — | Only include files changed since this git ref |
| `--print` | off | Print to stdout (use with pipe) |
| `--session` | off | Re-pack on every file change (watch mode) |
| `--refresh` | off | Force rebuild summaries before packing |

**Budget modes:**

| Mode | What's included |
|------|----------------|
| `minimal` | Changed files + direct configs only |
| `balanced` | Changed files + deps + reverse deps + tests + summaries |
| `deep` | Everything in balanced + docs + more full-content files |

---

### `agentpack scan`

Scan the repo and report file statistics.

```
Files discovered:     1,248
Files ignored/binary:   230
Files scanned:          210
Raw estimated tokens: 940,000
Tokens after ignore:  210,000
```

---

### `agentpack stats`

Show token statistics for the last pack vs. realistic alternatives.

```
Raw repo tokens:        940,000
After ignore:           210,000
Packed tokens:           24,000
vs. manual assembly:    ~65,000   (estimated hand-picked context)
Files ignored:            1,230
Files included (full):       18
Files summarized:            12
```

---

### `agentpack status`

Check whether the context pack is stale.

```bash
agentpack status
# Context pack is up to date.
#   Task: fix auth session bug
#   Generated: 2026-04-28T18:06:02Z
```

---

### `agentpack diff`

Show changes since last snapshot.

```
Added:    3 files
Modified: 7 files
Deleted:  1 file
Unchanged: 202 files
```

---

### `agentpack monitor`

Show pack performance across runs — timing per phase, token savings trend.

```bash
agentpack monitor           # last 20 runs
agentpack monitor --last 5  # last 5 runs
agentpack monitor --clear   # wipe metrics log
```

---

## Claude Code slash command

For Claude Code sessions where you want a pre-built context snapshot (useful on large repos where initial exploration is slow):

```bash
agentpack install --agent claude    # installs /agentpack globally
```

Then inside Claude Code:

```
/agentpack --task "fix Redis SSE cancellation issue"
```

This is a convenience wrapper — it packs and reads the context, then starts working. On small repos where Claude Code's tool calls are fast, you won't notice a difference. On large repos (>100 files of active code), pre-packing can reduce tool-call overhead on the first turn.

---

## How it works

```
1. Scan repo  →  apply .agentignore  →  hash every file
2. Build current snapshot  →  diff against previous snapshot
3. Get git changed/staged files  (+ --since <ref> if specified)
4. Build Python/JS/TS/Go/Rust/Java import dependency graph
5. Detect related test files
6. Extract task keywords  →  score every file
7. Rank by score, select within token budget
8. For each selected file:
     changed + small  →  full content
     changed + large  →  symbol bodies (ast.get_source_segment, no re-read)
     unchanged dep    →  summary + symbol signatures
     low-score file   →  summary only
9. Generate context receipts (why each file included/excluded)
10. Render Claude markdown  →  save context pack
11. Save snapshot + metadata + metrics
```

---

## File scoring

| Signal | Points |
|--------|-------:|
| Modified file | +100 |
| Staged file | +90 |
| Filename/path keyword match | +80 |
| Symbol keyword match | +70 |
| Content keyword match | +60 |
| Direct dependency of changed file | +50 |
| Reverse dependency | +40 |
| Has related tests | +35 |
| Config file | +25 |
| Recently modified | +20 |
| Large unrelated file | −50 |
| Ignored/binary | −100 |

---

## Configuration

`.agentpack/config.toml`:

```toml
[project]
root = "."
ignore_file = ".agentignore"

[context]
default_budget = 25000
default_mode = "balanced"
max_file_tokens = 4000
include_tests = true
include_configs = true
include_receipts = true

[summary]
provider = "offline"
schema_version = 1

[agents.claude]
output = ".agentpack/context.claude.md"
patch_claude_md = true

[agents.generic]
output = ".agentpack/context.md"
```

---

## Configurable scoring weights

```toml
[scoring]
modified                  = 100
staged                    = 90
filename_keyword          = 80
symbol_keyword            = 70
content_keyword_per_hit   = 10
content_keyword_max       = 60
direct_dep                = 50
reverse_dep               = 40
related_test              = 35
config_file               = 25
recently_modified         = 20
large_unrelated_penalty   = -50
ignored_penalty           = -100
```

---

## .agentignore

Works like `.gitignore`. Default rules exclude:

- `node_modules/`, `.venv/`, `__pycache__/`
- `dist/`, `build/`, `.next/`, `coverage/`
- `*.lock`, `*.log`, `*.min.js`, `*.map`
- `.env`, `.env.*`, `*.pem`, `*.key`
- `*.csv`, `*.jsonl`, `*.parquet`

---

## Git integration

```
.agentignore              ✓ commit
.agentpack/config.toml    ✓ commit
.agentpack/cache/         ✓ commit if --share-cache (recommended for teams)
.agentpack/snapshots/     ✗ gitignored
.agentpack/context.*      ✗ gitignored
```

---

## Architecture

### Data flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        agentpack pack                               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │              SCAN LAYER                  │
          │                                         │
          │  pathlib.rglob()  ──▶  .agentignore     │
          │       │                 (pathspec)       │
          │       ▼                                  │
          │  FileInfo[]  (path, hash, tokens, lang) │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │            ANALYSIS LAYER                │
          │                                         │
          │  Import graph  ──  Python AST           │
          │  (6 languages)  ─  JS/TS regex          │
          │                 ─  Go regex              │
          │                 ─  Rust regex            │
          │                 ─  Java/Kotlin regex     │
          │                                         │
          │  Symbol extract  ── Python AST          │
          │    (body via       ── JS/TS regex       │
          │  ast.get_source_                        │
          │  segment — no re-read)                  │
          │                                         │
          │  Test detection  ── name heuristics     │
          │  Task keywords   ── stopwords + variants│
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │     SUMMARY CACHE  (offline, local)      │
          │                                         │
          │  key: path + hash + provider + schema   │
          │  hit  → instant, zero I/O               │
          │  miss → build from AST/regex, cache it  │
          │                                         │
          │  offline  ──  AST / regex extract       │
          │  claude   ──  Haiku API (optional)      │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │           CHANGE DETECTION               │
          │                                         │
          │  Snapshot diff  (merkle root hash)      │
          │       +                                 │
          │  git diff / git diff --cached           │
          │       +                                 │
          │  git diff <ref> HEAD  (--since flag)    │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │              RANKING                     │
          │                                         │
          │  Score each file (configurable weights) │
          │  +100 modified  +80 filename match      │
          │   +70 symbol    +60 content match       │
          │   +50 dep       +40 rev-dep             │
          │   +35 test      +25 config  +20 recent  │
          │   -50 large unrelated                   │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │         BUDGET SELECTION                 │
          │                                         │
          │  Sort by score, consume until budget    │
          │                                         │
          │  changed + small  ──▶  full content     │
          │  changed + large  ──▶  symbol bodies    │
          │  unchanged dep    ──▶  summary + sigs   │
          │  low score        ──▶  summary only     │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │              RENDERING                   │
          │                                         │
          │  Claude adapter  ──▶  context.claude.md │
          │  Generic adapter ──▶  context.md        │
          │                                         │
          │  Context receipts (why each file in/out)│
          │  Staleness warning if snapshot drifted  │
          └─────────────────────────────────────────┘
```

### Package layout

```
src/agentpack/
  cli.py                       # Typer CLI — all commands
  data/
    agentpack.md               # bundled /agentpack slash command for Claude CLI

  core/
    models.py                  # Pydantic: FileInfo, Symbol, FileSummary, ContextPack
    config.py                  # TOML config + ScoringWeights
    ignore.py                  # .agentignore / gitignore-style matching
    scanner.py                 # pathlib rglob, binary detection, token estimation
    snapshot.py                # JSON snapshots + merkle root hash
    diff.py                    # added / modified / deleted / unchanged diff
    git.py                     # subprocess git (graceful fallback)
    merkle.py                  # root hash: sort(path:hash) → sha256
    cache.py                   # summary cache keyed path+hash+provider+version
    context_pack.py            # file selection algorithm + pack metadata
    token_estimator.py         # tiktoken cl100k_base (exact counts)

  analysis/
    python_imports.py          # ast-based import extraction
    js_ts_imports.py           # regex import extraction (ESM + CJS)
    go_imports.py              # Go import / import(...) blocks
    rust_imports.py            # use, mod, extern crate
    java_imports.py            # Java import + Kotlin import
    symbols.py                 # AST symbols + body via ast.get_source_segment
    tests.py                   # source → test file mapping heuristics
    ranking.py                 # keyword extraction + configurable scoring

  summaries/
    offline.py                 # zero-API: AST/regex → imports, symbols, summary
    llm.py                     # Claude Haiku API summaries (optional)
    base.py                    # cache-or-build orchestration

  adapters/
    base.py                    # abstract BaseAdapter
    claude.py                  # context.claude.md + CLAUDE.md safe patching
    generic.py                 # context.md

  renderers/
    markdown.py                # full/symbols/summary mode markdown renderer
    receipts.py                # context receipt formatter
```

---

## Tips & tricks

### Let `--task auto` do the work

Skip writing a task description — agentpack infers it from your branch name, changed files, and recent commits:

```bash
agentpack pack --task auto --print | claude
```

Priority order: branch name → changed file paths → recent commit message. The more descriptive your branch names (`feat/add-rate-limiting` beats `dev`), the better the inferred task.

### Boost keyword coverage automatically

When you run `agentpack pack`, changed file content is scanned for high-frequency identifiers. If you're editing `session_manager.py` that mentions `validate_token` 30 times, `validate` and `token` are added as keywords automatically — related files that use the same terms get a score boost even if your task string didn't mention them.

### Commit the summary cache for instant team packs

```bash
agentpack init --share-cache
git add .agentpack/cache/
git commit -m "chore: add agentpack summary cache"
```

Every teammate and CI job now skips the summarize step. `agentpack pack` takes under 100ms from a warm cache.

### Use `--since` for PR reviews

```bash
agentpack pack --task "review auth changes" --since main --print | claude
```

Only includes files changed since `main`. Cuts out noise from unrelated work in long-running branches.

### Tune the budget for your use case

```bash
agentpack pack --task "fix bug" --mode minimal   # changed files only, fewest tokens
agentpack pack --task "refactor" --mode deep     # everything including docs
agentpack pack --task "fix bug" --budget 40000   # explicit token cap
```

`balanced` (default) is right for most tasks. Use `minimal` for quick fixes, `deep` when architectural context matters.

### Watch mode for active sessions

```bash
agentpack pack --task "refactor auth" --session
```

Repacks every time you save a file. Pipe the output file into Claude separately:

```bash
# In one terminal:
agentpack pack --task "refactor auth" --session

# In another:
claude < .agentpack/context.claude.md
```

### Auto-repack in Claude Code via hook

Add to `.claude/settings.json` to auto-repack when stale at the start of each prompt:

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "result=$(agentpack status 2>&1); code=$?; if [ $code -ne 0 ]; then agentpack pack --task auto --mode balanced 2>/dev/null && echo '{\"hookSpecificOutput\": {\"hookEventName\": \"UserPromptSubmit\", \"additionalContext\": \"agentpack context was stale and has been auto-repacked\"}}'; fi",
        "timeout": 15
      }]
    }]
  }
}
```

Stale = silent repack. Fresh = zero overhead.

### Raise scoring weights for your codebase

If tests are always irrelevant to your tasks, drop their weight. If config files are critical, raise them:

```toml
# .agentpack/config.toml
[scoring]
related_test    = 5    # was 35 — tests rarely relevant
config_file     = 60   # was 25 — configs always matter here
```

### Check what got included and why

Every pack includes a context receipt explaining each file's inclusion or exclusion:

```
- `src/auth.py` included because modified, filename keyword match
- `tests/test_auth.py` summarized because test for src/auth.py
- `src/unrelated_big.py` excluded because score too low
```

Use this to tune your `.agentignore` or scoring weights when irrelevant files keep appearing.

---

## Principles

- **Local-first**: `init`, `scan`, `diff`, `pack`, `stats`, `summarize` make zero API calls by default
- **Non-destructive**: never overwrites user files; CLAUDE.md patching only touches the AgentPack-managed block
- **Agent-neutral**: architecture is generic; Claude is the first-class adapter
- **No daemons**: file watching is opt-in via `--session`; nothing runs in the background otherwise
- **Honest**: packed token count reflects real content, not raw repo size

---

## Optional dependencies

tiktoken is included by default.

```bash
pip install "agentpack[llm]"      # anthropic — LLM summaries via Claude Haiku
pip install "agentpack[watch]"    # watchdog — --session watch mode
pip install "agentpack[all]"      # llm + watch
```

---

## License

MIT
