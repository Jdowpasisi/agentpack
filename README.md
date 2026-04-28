# AgentPack

**Pack only what your coding agent needs.**

AgentPack scans your repo, ignores noise, detects changes, ranks relevant files, summarizes unchanged code, and generates compact context packs for Claude CLI and other AI coding agents.

- Saves tokens — typical savings: 70–97%
- Focuses Claude on files that matter for the task
- Fully local by default — no LLM API calls, no network requests
- Works with Claude CLI, Claude Code, and other agents

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
agentpack pack --agent claude --task "fix auth session bug"
claude < .agentpack/context.claude.md
```

Or pipe directly:

```bash
agentpack pack --agent claude --task "fix auth session bug" --print | claude
```

---

## Claude CLI slash command

Install the `/agentpack` slash command so you can run it directly inside any Claude CLI session:

```bash
agentpack install --agent claude
```

This does three things:
1. Patches `CLAUDE.md` with an AgentPack context block
2. Installs `~/.claude/commands/agentpack.md` globally (available in all repos)

Then inside Claude CLI:

```
/agentpack                          # init + pack with balanced mode
/agentpack --task "fix Redis SSE cancellation issue"
/agentpack status                   # is pack stale?
/agentpack stats                    # token savings report
/agentpack diff                     # changed files since last snapshot
```

To install locally for just this repo (`.claude/commands/agentpack.md`):

```bash
agentpack install --agent claude --local
```

---

## Commands

### `agentpack init`

Initialize AgentPack in the current directory.

Creates:
```
.agentignore              # gitignore-style file exclusion rules
.agentpack/
  config.toml             # configuration (safe to commit)
  .gitignore              # excludes cache/, snapshots/, context.*
  cache/                  # offline summary cache (gitignored)
  snapshots/              # file hash snapshots (gitignored)
```

Won't overwrite existing files unless `--force` is passed.

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

### `agentpack pack`

Main command. Generates a context pack for the target agent.

```bash
agentpack pack --agent claude --task "fix Redis SSE cancellation issue"
agentpack pack --agent claude --task "fix Redis SSE cancellation issue" --mode deep
agentpack pack --agent claude --task "..." --budget 15000
agentpack pack --agent claude --task "..." --print | claude
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--agent` | `claude` | Target agent (`claude` or `generic`) |
| `--task` | required | One-line description of the task |
| `--mode` | `balanced` | Budget mode: `minimal`, `balanced`, `deep` |
| `--budget` | 25000 | Token budget (0 = use config default) |
| `--print` | off | Print context to stdout instead of file |
| `--refresh` | off | Rebuild summaries before packing |
| `--summary-provider` | `offline` | Summary provider (only `offline` in v1) |

**Budget modes:**

| Mode | What's included |
|------|----------------|
| `minimal` | Changed files + direct configs only |
| `balanced` | Changed files + dependencies + reverse deps + tests + summaries |
| `deep` | Everything in balanced + docs + more full-content files |

**Output:** `.agentpack/context.claude.md`

---

### `agentpack install`

Patch `CLAUDE.md` and install the `/agentpack` slash command.

```bash
agentpack install --agent claude            # global (~/.claude/commands/)
agentpack install --agent claude --local    # local (.claude/commands/)
agentpack install --agent claude --no-slash-command   # CLAUDE.md only
```

---

### `agentpack status`

Check whether the latest context pack is stale.

A pack is stale if any files changed since it was generated (detected via snapshot hash comparison).

```bash
agentpack status
# Context pack is up to date.
#   Task: fix auth session bug
#   Generated: 2026-04-28T18:06:02Z

# or:
# Context pack is STALE. Run agentpack pack to refresh.
```

---

### `agentpack stats`

Show token-saving statistics.

```
Raw repo tokens:    940,000
After ignore:       210,000
Packed tokens:       24,000
Estimated saving:     97.4%
Files ignored:        1,230
Files included (full):   18
Files summarized:        12
```

---

### `agentpack diff`

Show changes since the last saved snapshot.

```
Added:    3 files
Modified: 7 files
Deleted:  1 file
Unchanged: 202 files
```

---

### `agentpack summarize`

Build or refresh the offline summary cache. No API calls.

```bash
agentpack summarize
agentpack summarize --refresh    # force rebuild all
```

---

## How it works

```
1. Scan repo  →  apply .agentignore  →  hash every file
2. Build current snapshot  →  diff against previous snapshot
3. Get git changed/staged files
4. Build Python/JS/TS import dependency graph
5. Detect related test files
6. Extract task keywords  →  score every file
7. Rank by score, select within token budget
8. For each selected file:
     changed + small  →  full content
     changed + large  →  symbols + summary
     unchanged dep    →  summary + symbols
     low-score file   →  summary only
9. Generate context receipts (why each file included/excluded)
10. Render Claude markdown  →  save context pack
11. Save snapshot + metadata
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

`.agentpack/config.toml` (created by `agentpack init`):

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

## .agentignore

Works like `.gitignore`. Default rules exclude:

- `node_modules/`, `.venv/`, `__pycache__/`
- `dist/`, `build/`, `.next/`, `coverage/`
- `*.lock`, `*.log`, `*.min.js`, `*.map`
- `.env`, `.env.*`, `*.pem`, `*.key`
- `*.csv`, `*.jsonl`, `*.parquet`

Add your own rules:

```gitignore
# team-specific
internal-docs/
*.generated.ts
fixtures/large/
```

---

## Git integration

What to commit:

```
.agentignore              ✓ commit
.agentpack/config.toml    ✓ commit
```

What's gitignored by default:

```
.agentpack/cache/         ✗ gitignored
.agentpack/snapshots/     ✗ gitignored
.agentpack/context.*      ✗ gitignored
```

---

## Architecture

```
src/agentpack/
  cli.py                  # Typer CLI — all 8 commands
  data/
    agentpack.md          # bundled /agentpack slash command
  core/
    models.py             # Pydantic models: FileInfo, Symbol, ContextPack, ...
    config.py             # TOML config load/save
    ignore.py             # .agentignore / gitignore-style matching
    scanner.py            # pathlib rglob, binary detection, token estimation
    snapshot.py           # JSON snapshots + merkle root hash
    diff.py               # added/modified/deleted/unchanged diff
    git.py                # subprocess git (graceful fallback if not in git repo)
    merkle.py             # root hash via sorted path:hash
    cache.py              # summary cache keyed by path+hash+provider+version
    context_pack.py       # file selection algorithm + pack metadata
    token_estimator.py    # len(text) // 4
  analysis/
    python_imports.py     # ast-based import extraction
    js_ts_imports.py      # regex-based import extraction
    symbols.py            # Python ast + JS regex symbol extraction
    tests.py              # test file detection heuristics
    ranking.py            # keyword extraction + file scoring
  summaries/
    offline.py            # zero-API summaries for Python/JS/TS/generic
    base.py               # cache-or-build orchestration
  adapters/
    claude.py             # context.claude.md + CLAUDE.md patching
    generic.py            # context.md
  renderers/
    markdown.py           # Claude markdown renderer
```

---

## Principles

- **Local-first**: `init`, `scan`, `diff`, `pack`, `stats`, `summarize` make zero API calls
- **Non-destructive**: never overwrites user files; CLAUDE.md patching only touches the AgentPack-managed block
- **Agent-neutral**: architecture is generic; Claude is the first-class adapter
- **No daemons**: no background processes, no file watchers, no VS Code extensions

---

## Optional dependencies

LLM-powered summaries (not used in v1 by default):

```bash
pip install "agentpack[llm]"
```

---

## License

MIT
