# AgentPack

> **Status: alpha (v0.1.0).** Works, tested, used in real sessions. Not yet validated across a wide range of repos. API may change before 1.0.

**Token-aware context packing for AI coding agents.**

---

## The problem

Every time you start a task with an AI coding agent, it has no idea what's in your repo. It either:

1. **Reads files on demand** (Claude Code, Cursor, Windsurf) — dozens of tool calls, paying exploration cost every session, every turn, forever.
2. **Gets the whole repo dumped in** (repomix, gitingest) — 50k–500k tokens of noise, most of it irrelevant to the task at hand.
3. **Gets nothing** — you hand-copy the 5 files you think matter and hope you got it right.

None of these scale. On a 200-file codebase, option 1 wastes 5–10 turns just orienting. Option 2 degrades output quality (LLMs perform worse on long noisy context). Option 3 misses critical dependencies and configs constantly.

**The root cause:** agents don't know *what's relevant to your current task* without doing the work to figure that out — which costs tokens, time, and money on every session.

---

## The solution

AgentPack solves this with a one-time offline analysis pass:

1. **Scans your repo once** — builds a summary cache of every file (signatures, imports, responsibilities). No API calls. Takes a few seconds.
2. **On each task** — uses git diff + import graph traversal + keyword scoring to rank every file by relevance to what you're working on.
3. **Packs a tight context document** — changed files get full content, dependencies get summaries, everything else gets dropped. Typically 8k–20k tokens for a 200-file repo.
4. **Stays current** — auto-repacks silently on commit, so next session starts fresh.

The result: your agent starts every session with a focused, accurate picture of the relevant code — without you doing anything.

```bash
# One-time global setup (works in every repo from that point on)
agentpack global-install --agent claude

# That's it. cd into any repo — agentpack silently bootstraps itself.
# Every Claude Code session gets focused context automatically.
```

Or for piped/API workflows:

```bash
agentpack pack --agent claude --task "fix auth session bug" --print | claude
```

Supported agents: **Claude Code**, **Cursor**, **Windsurf**, **Codex**, or any LLM via pipe/API.

---

## When it helps

| Workflow | Value |
|---|---|
| `agentpack pack --print \| claude` — piped, no tools | **High** — Claude has no file access; pack is its only context |
| `claude < .agentpack/context.claude.md` — stdin | **High** — same |
| Claude API calls without tool use | **High** — same |
| CI: generate pack per PR, attach as artifact | **High** — reviewers get instant focused context |
| Cursor / Windsurf / Codex sessions | **Medium** — context auto-injected on startup, repacked on commit |
| Large repos (>50k tokens) where exploration is slow | **Medium** — summary cache eliminates repeated file reads |
| Claude Code interactive session, small repo | **Low** — Claude reads files on demand already |

---

## How it compares to alternatives

**The honest version.**

### repomix / gitingest / code2prompt

These are repo dumpers. They pack a repo (or subset) into a file and hand it to you. They do that job well.

What they don't do: decide what's relevant to *your task*. You specify the scope — files, globs, directories — and they package your decision. If you want "only the files that matter for fixing this auth bug", you have to figure that out yourself. On a 200-file repo, that's 80% of the work.

AgentPack does that selection automatically. You give it a task string; it uses git diff, import graph traversal, and keyword scoring to rank every file, then cuts to fit your token budget. You don't touch globs.

The other difference: all three pack uniformly (full content or nothing). AgentPack is selective by inclusion mode — changed files get full content, unchanged deps get summaries, unrelated files get dropped. A repomix dump of a 50k-token repo stays 50k tokens. An agentpack of the same repo for a specific task is typically 8k–20k.

**Use repomix/gitingest if:** you want to dump an entire small repo into a chat UI for a one-shot question. Zero setup, great for "explain this codebase."

**Use agentpack if:** you're running repeated tasks on a large repo and want automatic, task-driven file selection every time.

### aider

Different category. Aider is an interactive pair programmer — it reads, edits, and commits files directly. Its repo-map is genuinely smart. If you want an AI coding assistant making actual edits, aider is excellent.

AgentPack is not a coding assistant. It's a context preparation tool. The output is a markdown file you pipe somewhere.

**Use aider if:** you want interactive, supervised AI coding sessions in a terminal.

**Use agentpack if:** you're driving Claude via pipe or API without an interactive session — CI, scripts, batch workflows.

### Claude Code / Cursor / Windsurf / Codex (agentic IDEs)

These tools have native file access via tool calls. Claude reads exactly the files it needs, on demand, per turn. Pre-packing context adds overhead without much benefit on small-to-medium repos.

AgentPack's value here is different: `agentpack install --agent <x>` configures your agent to auto-inject a ranked context pack on session start and auto-repack whenever you commit. On large repos where tool-call exploration piles up across turns, this front-loads the cost once instead of paying per-turn.

### Where agentpack genuinely wins

| Scenario | repomix | gitingest | code2prompt | aider | agentpack |
|---|---|---|---|---|---|
| Piped CLI (`... \| claude`) | ✓ dump | ✓ dump | ✓ dump | ✗ | ✓ task-filtered |
| API call without tool use | ✓ dump | ✗ | ✓ | ✗ | ✓ task-filtered |
| CI per-PR context | ✓ dump | ✗ | ✓ | ✗ | ✓ task-filtered |
| Auto task inference from git | ✗ | ✗ | ✗ | partial | ✓ |
| Relevance ranking by task | ✗ | ✗ | ✗ | ✗ | ✓ |
| Import graph traversal | ✗ | ✗ | ✗ | ✓ | ✓ |
| Token budget enforcement | manual | manual | manual | ✓ | ✓ |
| Cursor / Windsurf / Codex install | ✗ | ✗ | ✗ | ✗ | ✓ |
| Zero API calls | ✓ | ✓ | ✓ | ✗ | ✓ |
| Interactive coding sessions | ✗ | ✗ | ✗ | ✓✓ | ✗ |
| Any LLM | ✓ | ✓ | ✓ | ✓ | partial* |

_*`--agent generic` outputs standard markdown. Claude adapter has richer instructions._

### What agentpack does NOT do well

- **Interactive sessions on small repos**: if your whole repo is <20k tokens, just use repomix
- **One-shot public repo questions**: gitingest's "replace hub with ingest" is faster for that
- **Semantic understanding**: keyword scoring + AST is not a language model — precise technical terms in your task description work better than vague ones

---

## Install

```bash
pip install agentpack
```

Requires Python 3.10+.

---

## Quickstart

### Option A: Global install (recommended — works in every repo forever)

```bash
pip install agentpack
agentpack global-install --agent claude   # or: cursor, windsurf, codex
```

That's it. This:
- Installs git template hooks into `~/.git-templates/` — git copies them into every future repo on `git init` or `git clone`
- Patches your shell rc (`~/.zshrc` / `~/.bashrc`) with a `cd` hook — silently bootstraps agentpack the first time you enter any git repo
- Configures your agent (Claude Code hooks, Cursor rules, etc.)

From that point on: `cd` into any project → agentpack silently self-configures. No `init`, no `summarize`, no `install` per project.

> Reload your shell once: `source ~/.zshrc`

### Option B: Per-project setup

```bash
cd your-project/
agentpack init
agentpack summarize              # build offline summary cache once
agentpack install --agent claude # configure your agent
```

### Option C: Piped / API / CI (no agent setup needed)

```bash
agentpack pack --agent claude --task "fix auth session bug" --print | claude
```

Save to file:

```bash
agentpack pack --agent claude --task "fix auth session bug"
claude < .agentpack/context.claude.md
```

---

## Agent setup

Run once per project. Each command is idempotent — safe to re-run, never clobbers unrelated config.

### Claude Code

```bash
agentpack install --agent claude
```

Configures:
- `CLAUDE.md` — tells Claude to read the context pack before each task
- `.claude/settings.json` — two hooks:
  - `SessionStart`: clears injection sentinel so first prompt gets context
  - `UserPromptSubmit`: auto-repacks when stale, injects context once per session

After this, context is injected automatically into every Claude Code session. No `/agentpack` command needed — it just happens.

### Cursor

```bash
agentpack install --agent cursor
```

Configures:
- `.cursorrules` — rule: read `.agentpack/context.md` before every conversation
- `.cursor/rules/agentpack.mdc` — `alwaysApply: true` rule (Cursor v0.43+)
- `.git/hooks/post-commit`, `post-merge`, `post-checkout` — background repack on tree change
- `.vscode/tasks.json` — "AgentPack: Repack context" in Command Palette + `runOn: folderOpen`

### Windsurf

```bash
agentpack install --agent windsurf
```

Configures:
- `.windsurfrules` — rule: read `.agentpack/context.md` before every conversation
- `.git/hooks/post-commit`, `post-merge`, `post-checkout` — background repack on tree change
- `.vscode/tasks.json` — "AgentPack: Repack context" in Command Palette + `runOn: folderOpen`

### Codex

```bash
agentpack install --agent codex
```

Configures:
- `AGENTS.md` — tells Codex to read the context pack before each task
- `.git/hooks/post-commit`, `post-merge`, `post-checkout` — background repack on tree change

### Auto-repack comparison

| Mechanism | Claude Code | Cursor | Windsurf | Codex |
|---|---|---|---|---|
| Config file patched | `CLAUDE.md` + `.claude/settings.json` | `.cursorrules` + `.cursor/rules/*.mdc` | `.windsurfrules` | `AGENTS.md` |
| Auto-inject on startup | ✅ `UserPromptSubmit` hook | ✅ `alwaysApply` | ✅ rules file | ✅ `AGENTS.md` |
| Auto-repack when stale | ✅ hook (per prompt) | ✅ git hooks | ✅ git hooks | ✅ git hooks |
| Manual repack shortcut | ✅ `/agentpack` slash cmd | ✅ VS Code task | ✅ VS Code task | `agentpack pack` |

---

## The summary cache — the core feature

Run once, reuse forever:

```bash
agentpack summarize
```

Builds an offline summary of every file — no API calls, no network. Each summary captures:
- What the file does and its responsibility
- Exported classes, functions, signatures with extracted bodies
- Import dependencies

Summaries are stored in `.agentpack/cache/` keyed by file hash. Only changed files are re-summarized on the next pack.

**Team tip:** commit the cache so every developer and CI job gets summaries for free:

```bash
agentpack init --share-cache
git add .agentpack/cache/
git commit -m "chore: add agentpack summary cache"
```

---

## Honest token framing

AgentPack's pack is typically 10,000–25,000 tokens. Comparing that to "raw repo size" (200k–2M tokens) is misleading — nobody dumps the whole repo into Claude.

The real comparison for a piped/API workflow: **what would you manually copy-paste** to give Claude enough context? For a typical bug fix touching 3 files with 10 relevant dependencies, that's ~30,000–80,000 tokens assembled by hand. AgentPack gets you there in one command.

Token counts use tiktoken `cl100k_base` — a close approximation to Claude's actual billing, but not exact.

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

### `agentpack global-install`

Install once — works in every repo from that point on. The recommended first step.

```bash
agentpack global-install --agent claude    # Claude Code
agentpack global-install --agent cursor    # Cursor
agentpack global-install --agent windsurf  # Windsurf
agentpack global-install --agent codex     # Codex
```

What it does:
- **Git template hooks** (`~/.git-templates/hooks/`) — git copies these into every repo on `git init` / `git clone`. Triggers silent repack on `post-commit`, `post-merge`, `post-checkout`.
- **Shell cd hook** (`~/.zshrc` or `~/.bashrc`) — runs `agentpack init --yes --silent` in the background the first time you `cd` into any git repo that isn't configured yet.
- **Agent config** — same as `agentpack install --agent <x>` for the current project.

All changes are idempotent, reversible, and non-destructive. Existing hooks and rc files are appended to, never overwritten.

Options:

| Flag | Default | Description |
|---|---|---|
| `--agent` | `claude` | Target agent |
| `--no-pipx` | — | Skip pipx install (if agentpack already installed) |
| `--no-shell-hook` | — | Skip shell rc patching |
| `--no-git-template` | — | Skip git template hooks |

---

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

### `agentpack install`

Configure agentpack for your AI coding agent.

```bash
agentpack install --agent claude    # CLAUDE.md + .claude/settings.json hooks
agentpack install --agent cursor    # .cursorrules + .mdc + git hooks + VS Code tasks
agentpack install --agent windsurf  # .windsurfrules + git hooks + VS Code tasks
agentpack install --agent codex     # AGENTS.md + git hooks
```

All installs are idempotent — safe to re-run, merge with existing config, never duplicate.

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
| `--agent` | `claude` | Target agent (`claude` \| `cursor` \| `windsurf` \| `codex` \| `generic`) |
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

### `agentpack explain`

Debug file selection: show which files would be selected, why, and what was excluded — without writing a context pack.

```bash
agentpack explain --task "fix auth session bug"
agentpack explain --task auto
```

Output:

```
Top selected files (ranked):
  1. src/auth/session.py        score=180  [full]     modified, filename keyword match
  2. src/auth/token.py          score=130  [symbols]  direct dependency of changed file
  3. tests/auth/test_session.py score=95   [summary]  test for src/auth/session.py

Files near budget cutoff:
  4. src/config/security.py     score=45   [summary]  content keyword match (2)

Excluded (top 5):
  - src/unrelated_big.py        score=12   budget exhausted
  - src/utils.py                score=8    score too low
```

Use this when a file you expected isn't showing up, or to tune `.agentignore` and scoring weights.

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

Show token statistics for the last pack.

```
Raw repo tokens:        940,000
After ignore:           210,000
Packed tokens:           24,000
vs. manual assembly:    ~65,000
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
#   Generated: 2026-04-29T12:00:00Z
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
agentpack monitor --last 5
agentpack monitor --clear
```

---

## How it works

```
1. Scan repo  →  apply .agentignore  →  hash every file
2. Build current snapshot  →  diff against previous snapshot
3. Get git changed/staged files  (+ --since <ref> if specified)
4. Build import dependency graph (Python/JS/TS: full; Go/Rust/Java: best-effort)
5. Detect related test files
6. Extract task keywords + concept synonym expansion
7. Enrich keywords from changed file content (high-frequency identifiers)
8. Score every file, rank by score
9. Select within token budget
10. For each selected file:
      changed + small  →  full content
      changed + large  →  symbol bodies (ast.get_source_segment)
      unchanged dep    →  summary + signatures
      low-score file   →  summary only
11. Generate context receipts (why each file included/excluded)
12. Render markdown for target agent  →  save context pack
13. Save snapshot + metadata + metrics
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

Keyword scoring uses concept synonym expansion — "rate limiting" in the task expands to `throttle`, `leaky`, `bucket`, `quota` etc., so `leaky_bucket.py` ranks correctly even if the file name doesn't literally contain "rate".

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
# .agentpack/config.toml
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
          │  ast.get_source_segment — no re-read)   │
          │                                         │
          │  Test detection  ── name heuristics     │
          │  Task keywords   ── stopwords + variants│
          │                  ── concept synonyms    │
          │                  ── content enrichment  │
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
          │  Cursor adapter  ──▶  context.md        │
          │  Windsurf adapter ─▶  context.md        │
          │  Codex adapter   ──▶  context.md        │
          │  Generic adapter ──▶  context.md        │
          │                                         │
          │  Context receipts (why each file in/out)│
          │  Secret redaction (AWS/GH/OpenAI tokens)│
          └─────────────────────────────────────────┘
```

### Package layout

```
src/agentpack/
  cli.py                       # Typer CLI entry point

  data/
    agentpack.md               # bundled /agentpack slash command for Claude CLI

  core/
    models.py                  # Pydantic: FileInfo, Symbol, FileSummary, ContextPack
    config.py                  # TOML config + ScoringWeights
    ignore.py                  # .agentignore / gitignore-style matching
    scanner.py                 # pathlib rglob, binary detection, token estimation
    snapshot.py                # JSON snapshots + merkle root hash
    diff.py                    # added / modified / deleted / unchanged diff
    git.py                     # subprocess git + task inference from branch/commits
    merkle.py                  # root hash: sort(path:hash) → sha256
    cache.py                   # summary cache keyed path+hash+provider+version
    context_pack.py            # file selection algorithm + pack metadata
    token_estimator.py         # tiktoken cl100k_base (approximate)
    redactor.py                # secret redaction before context render
    git_hooks.py               # install/remove post-commit/merge/checkout hooks
    vscode_tasks.py            # install/remove .vscode/tasks.json entries

  analysis/
    python_imports.py          # ast-based import extraction
    js_ts_imports.py           # regex import extraction (ESM + CJS)
    go_imports.py              # Go import / import(...) blocks
    rust_imports.py            # use, mod, extern crate
    java_imports.py            # Java import + Kotlin import
    symbols.py                 # AST symbols + body via ast.get_source_segment
    tests.py                   # source → test file mapping heuristics
    ranking.py                 # keyword extraction, concept synonyms, scoring

  summaries/
    offline.py                 # zero-API: AST/regex → imports, symbols, summary
    llm.py                     # Claude Haiku API summaries (optional)
    base.py                    # cache-or-build orchestration

  adapters/
    base.py                    # abstract BaseAdapter
    claude.py                  # CLAUDE.md + .claude/settings.json hooks
    cursor.py                  # .cursorrules + .cursor/rules/*.mdc
    windsurf.py                # .windsurfrules
    codex.py                   # AGENTS.md
    generic.py                 # context.md (any LLM)

  renderers/
    markdown.py                # full/symbols/summary mode renderer + secret redaction
    receipts.py                # context receipt formatter

  commands/
    pack.py                    # agentpack pack
    install.py                 # agentpack install / global-install
    init.py                    # agentpack init
    scan.py                    # agentpack scan
    diff.py                    # agentpack diff
    status.py                  # agentpack status
    stats.py                   # agentpack stats
    summarize.py               # agentpack summarize
    monitor.py                 # agentpack monitor
    explain.py                 # agentpack explain
```

---

## Tips & tricks

### Let `--task auto` do the work

Skip writing a task description — agentpack infers it from your branch name, changed files, and recent commits:

```bash
agentpack pack --task auto --print | claude
```

Priority order: branch name → changed file paths → recent commit message. The more descriptive your branch names (`feat/add-rate-limiting` beats `dev`), the better the inferred task.

### Concept synonym expansion

AgentPack expands task keywords automatically — "rate limiting" expands to `throttle`, `leaky`, `bucket`, `quota`, `debounce`; "auth" expands to `jwt`, `bearer`, `token`, `oauth`; "cache" expands to `lru`, `memoize`, `redis`, `ttl`. Files that implement a concept but don't use its exact name still rank correctly.

### Content-based keyword enrichment

When you run `agentpack pack`, changed file content is scanned for high-frequency identifiers. If you're editing `session_manager.py` that mentions `validate_token` 30 times, `validate` and `token` are added as keywords — related files that use the same terms get a score boost even if your task string didn't mention them.

### Commit the summary cache for instant team packs

```bash
agentpack init --share-cache
git add .agentpack/cache/
git commit -m "chore: add agentpack summary cache"
```

Every teammate and CI job skips the summarize step. `agentpack pack` is significantly faster from a warm cache.

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

Repacks every time you save a file.

### Debug file selection with `explain`

```bash
agentpack explain --task "fix auth session bug"
```

Shows ranked scores and reasons before committing to a pack. Use when a file you expect isn't appearing.

### Check what got included and why

Every pack includes a context receipt explaining each file's inclusion or exclusion:

```
- `src/auth.py` included because modified, filename keyword match
- `tests/test_auth.py` summarized because test for src/auth.py
- `src/unrelated_big.py` excluded because score too low
```

Use this to tune your `.agentignore` or scoring weights when irrelevant files keep appearing.

### Tune scoring weights per project

If tests are always irrelevant to your tasks, drop their weight. If config files are critical, raise them:

```toml
# .agentpack/config.toml
[scoring]
related_test    = 5    # was 35 — tests rarely relevant
config_file     = 60   # was 25 — configs always matter here
```

---

## Principles

- **Local-first**: `init`, `scan`, `diff`, `pack`, `stats`, `summarize` make zero API calls by default
- **Non-destructive**: never overwrites user files; config patching only touches agentpack-managed blocks
- **Agent-neutral**: architecture is generic; Claude, Cursor, Windsurf, and Codex are all first-class
- **No daemons**: file watching is opt-in via `--session`; git hooks run in the background and are opt-in via `install`
- **Honest**: packed token count reflects real content, not raw repo size

---

## Optional dependencies

```bash
pip install "agentpack[llm]"      # anthropic — LLM summaries via Claude Haiku
pip install "agentpack[watch]"    # watchdog — --session watch mode
pip install "agentpack[all]"      # llm + watch
```

---

## License

MIT
