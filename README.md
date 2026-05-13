# AgentPack

[![PyPI version](https://img.shields.io/pypi/v/agentpack-cli.svg)](https://pypi.org/project/agentpack-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/agentpack-cli.svg)](https://pypi.org/project/agentpack-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/vishal2612200/agentpack/actions/workflows/ci.yml/badge.svg)](https://github.com/vishal2612200/agentpack/actions/workflows/ci.yml)

> **Status: alpha (v0.1.23).** Works, tested, used in real sessions. Python and JavaScript/TypeScript are the best-supported languages. Not yet validated across a wide range of repos. API may change before 1.0.
>
> **Platform note:** macOS and Linux are fully supported. Windows support is not yet implemented (git hooks use POSIX shell; the Claude Code session hooks use `python3`/`rm -f`). Contributions welcome.

**Task-aware context packing for AI coding agents.**

AgentPack scans a repository, ranks files for the task you are working on, and writes a compact markdown context pack for Claude Code, Cursor, Windsurf, Codex, Antigravity, CI jobs, or any LLM workflow.

It is useful when the repo is too large to paste, but you still want the agent to start with more than a blank slate.

**What it is**
- A local CLI for building task-focused context packs
- A summary cache, import graph, ranking engine, and token-budget selector
- Optional integrations for popular coding agents
- An eval harness for measuring whether selected files match files you actually changed

**What it is not**
- Not a coding agent
- Not a semantic code search engine
- Not a replacement for manual inspection on high-stakes changes
- Not yet proven across a large public benchmark suite

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
2. **On each task** — uses git diff, import graph traversal, keyword/concept expansion, implementation-role boosts, and cross-layer relatedness to rank every file.
3. **Packs a tight context document** — changed files get full content, large changed files get relevant symbol bodies, dependencies and likely implementation files get summaries, everything else gets dropped.
4. **Explains pack quality** — noisy-pack diagnostics, score receipts, token-precision metrics, and benchmark miss reports show when the pack is broad or missing expected files.
5. **Stays current** — auto-repacks silently on commit, so next session starts fresh.

The result: your agent starts with a focused map of the relevant code. It should reduce blind exploration, not replace the agent's own file reads or your judgment.

```bash
pip install agentpack-cli

# Show the fastest path for your repo
agentpack quickstart --task "fix auth token expiry"

# One-time setup per project
cd your-project
agentpack init             # creates config, session, task.md — nothing else needed
agentpack install          # auto-detects your IDE (optional but recommended)

# Every terminal session
agentpack watch            # keeps context fresh automatically — that's it
```

Then open Claude Code / Cursor / Windsurf / Codex / Antigravity and write your task normally. AgentPack keeps `.agentpack/context.md` current.

For power users who want background repacking on every commit and cd:

```bash
# Advanced: global automation (opt-in repos only — never touches repos without .agentpack/)
agentpack global-install --dry-run   # preview first
agentpack global-install
```

Supported agents: **Claude Code**, **Cursor**, **Windsurf**, **Codex**, **Antigravity** (Google), or any LLM that can read markdown.

---

## What to expect

AgentPack's strongest value is repeatable orientation: it gives the agent a compact first-pass map before tool calls begin.

Typical results on large repos:

| Signal | What good looks like |
|---|---|
| Token reduction | 90-99% smaller than raw repo text |
| Pack size | Usually 8k-25k tokens for a specific task |
| Pack time | Seconds on warm cache; first summarize pass is slower |
| Recall | Should be high for files you later edit; validate with `agentpack benchmark` |
| Precision | Often modest; summaries are cheap but can still add noise |

The compression number is easy to verify, but it is not the same as usefulness. The important question is: **did AgentPack include the files you actually needed?**

Use the built-in eval flow:

```bash
agentpack benchmark --init
# add real historical tasks and files you actually changed
agentpack benchmark --compare --misses
```

For source checkouts, there is also a small smoke suite:

```bash
agentpack benchmark --sample-fixtures --misses
```

This runs FastAPI, Next.js, and mixed Python/TypeScript fixture tasks. It is a sanity check, not a substitute for real repo evals.

### Current quality bar

AgentPack is best described as a **map, not a compass**. It is already good at token reduction, changed-file inclusion, related tests, imports, configs, and common concepts like auth/cache/rate limiting. Recent ranking work also improves full-stack tasks by pulling service/controller/schema/handler files when UI routes or pages match the same domain.

Known weak spot: recall can still be low on unfamiliar product domains or cross-language flows. Use `benchmark --misses` and `agentpack explain` when an expected file is absent. Those commands show whether the miss was caused by ignore rules, low score, summary floor, budget cutoff, or missing task signal.

### Observed author-run numbers

These are local author-session numbers, included as anecdotal context rather than a benchmark claim.

#### Token Compression

| Metric | Value |
|--------|-------|
| Sessions | 21 |
| Avg compression | 99.3% |
| Min / Max | 98.7% → 99.9% |
| Total raw (theoretical) | 116.9M tokens |
| Total packed (actual) | 683K tokens |

Per session: ~4.1M raw repo → ~35K packed context.

#### Cost (Sonnet 4.6, input tokens only)

| Scenario | Cost |
|----------|------|
| Full repo dumped each run | ~$350 |
| With AgentPack | ~$2.05 |
| **Realistic** (10% manual cherry-pick baseline) | **~$33 saved** |

> Honest note: raw_tokens = full repo estimate. Real savings depend on how much context you'd pass manually. Compression ratio (99%+) is verifiable; dollar figure is scenario-dependent.

#### Quality Signal

- 42 commits in 7 days (~6/day) vs 4.9/day before
- Shift from single-file fixes → multi-system coordinated fixes
- AgentPack provides dependent files + callers in context → fixes root cause, not symptom
- Correlation observed, causation not isolated

---

## When it helps

| Workflow | Value |
|---|---|
| Claude API calls without tool use | **High** — pack is the only context the model sees |
| CI: generate pack per PR, attach as artifact | **High** — reviewers get instant focused context |
| Cursor / Windsurf / Codex / Antigravity sessions | **Medium** — context auto-injected on startup, repacked on commit |
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

AgentPack is not a coding assistant. It's a context preparation tool. The output is a markdown file you can pass as context.

**Use aider if:** you want interactive, supervised AI coding sessions in a terminal.

**Use agentpack if:** you're working on large repos and want automatic, task-driven file selection — CI, scripts, batch workflows, or interactive sessions.

### Claude Code / Cursor / Windsurf / Codex (agentic IDEs)

These tools have native file access via tool calls. Claude reads exactly the files it needs, on demand, per turn. Pre-packing context adds overhead without much benefit on small-to-medium repos.

AgentPack's value here is different: `agentpack install --agent <x>` configures your agent to auto-inject a ranked context pack on session start and auto-repack whenever you commit. On large repos where tool-call exploration piles up across turns, this front-loads the cost once instead of paying per-turn.

### Where agentpack genuinely wins

| Scenario | repomix | gitingest | code2prompt | aider | agentpack |
|---|---|---|---|---|---|
| API call without tool use | ✓ dump | ✗ | ✓ | ✗ | ✓ task-filtered |
| CI per-PR context | ✓ dump | ✗ | ✓ | ✗ | ✓ task-filtered |
| Auto task inference from git | ✗ | ✗ | ✗ | partial | ✓ |
| Relevance ranking by task | ✗ | ✗ | ✗ | ✗ | ✓ |
| Import graph traversal | ✗ | ✗ | ✗ | ✓ | ✓ |
| Token budget enforcement | manual | manual | manual | ✓ | ✓ |
| Cursor / Windsurf / Codex / Antigravity install | ✗ | ✗ | ✗ | ✗ | ✓ |
| Zero API calls | ✓ | ✓ | ✓ | ✗ | ✓ |
| Interactive coding sessions | ✗ | ✗ | ✗ | ✓✓ | ✗ |
| Any LLM | ✓ | ✓ | ✓ | ✓ | partial* |

_*`--agent generic` outputs standard markdown. Claude adapter has richer instructions._

### What agentpack does NOT do well

- **Interactive sessions on small repos**: if your whole repo is <20k tokens, a simple repo dump may be enough
- **One-shot public repo questions**: gitingest's "replace hub with ingest" is faster for quick read-only exploration
- **Guaranteed source-of-truth selection**: AgentPack ranks likely files; it can miss task-critical files. Use `agentpack benchmark --misses`, `agentpack explain`, and normal `rg`/agent file reads for correctness.
- **Deep semantic understanding**: keyword/concept scoring, imports, symbols, and path roles help, but they are not an LLM-level code understanding system

---

## Install

```bash
pip install agentpack-cli
```

Requires Python 3.10+.

> **PyPI note:** The package is `agentpack-cli` (the name `agentpack` was already taken). The CLI command is still `agentpack`.

### npm wrapper

AgentPack can also be installed from npm:

```bash
npm install -g @vishal2612200/agentpack
agentpack --version
```

The npm package is a thin Node.js wrapper around the Python CLI. It requires Node.js 18+ and Python 3.10+, then installs the matching `agentpack-cli` PyPI package into a per-version virtual environment on first run. This keeps the implementation single-source while giving JavaScript-heavy teams a familiar install path.

---

## Start Once, Then Work Normally

For a guided two-minute path in any repo:

```bash
agentpack quickstart --task "fix auth token expiry"
```

It shows the exact commands to initialize, set task text, generate a first pack, inspect stats, start watch mode, and scaffold a small benchmark file for your own tasks.

The full workflow:

```bash
# One-time project setup
agentpack init             # creates config, session, task.md
agentpack install          # configure your agent (optional but recommended)

# Every terminal session — just one command
agentpack watch            # auto-resumes session, refreshes context on file/task changes
```

Then open Claude Code / Cursor / Codex and write your coding task normally.

- AgentPack keeps `.agentpack/context.md` and `.agentpack/context.claude.md` fresh while `watch` is running.
- To change the task: edit `.agentpack/task.md` directly, or tell Claude — it updates the file itself. `watch` picks up the change automatically.

### Agent integration matrix

| Agent | Automation level | Method |
|---|---|---|
| Claude Code (hook) | Highest | `UserPromptSubmit` hook auto-injects context |
| Codex | Medium | `AGENTS.md` + `init` + `watch` |
| Cursor | Medium | `.cursor/rules/agentpack.mdc` + `init` + `watch` |
| Windsurf | Medium | `.windsurfrules` + `init` + `watch` |
| Antigravity | Medium | `.agent/skills/agentpack/SKILL.md` + `GEMINI.md` + `init` + `watch` |
| Generic | Basic | `watch` mode + read `context.md` |

### Honest limitations

- AgentPack cannot intercept prompts inside IDEs — Cursor/Windsurf rely on rules being followed.
- Claude wrapper (`agentpack claude`) is the most deterministic integration.
- If the task changes drastically mid-session, context needs one refresh cycle.
- AgentPack-selected files are ranked starting points, not absolute truth.

---

## Quickstart

```bash
pip install agentpack-cli
cd your-project
agentpack init             # one-time setup: config + session + task.md
agentpack install          # auto-detects your IDE (Claude Code, Cursor, Windsurf, Codex, Antigravity)
agentpack watch            # in another terminal — keeps context fresh automatically
```

Then open your agent and write your task normally.

**Power users (global automation):**

```bash
agentpack global-install --dry-run   # preview
agentpack global-install             # apply
source ~/.zshrc
```

Then opt each project in: `cd your-project && agentpack init`. After that git hooks repack on commit and the Claude Code hook injects context on every session start — no manual steps.

---

## Agent setup

Run once per project. Each command is idempotent — safe to re-run, never clobbers unrelated config.

`agentpack install` without `--agent` auto-detects the active IDE from environment variables and project files. Pass `--agent` explicitly to override.

### Claude Code

```bash
agentpack install --agent claude
```

Configures:
- `CLAUDE.md` — tells Claude to read the context pack before each task
- `.claude/settings.json` — two hooks:
  - `SessionStart`: clears injection sentinel so first prompt gets context
  - `UserPromptSubmit`: runs `agentpack hook` — detects repo changes via `root_hash`, triggers background repack using your prompt as task. With MCP: emits Option-B hint (~100 tokens, task + top files). Without MCP: emits capped fallback (top 8 files, ≤3k chars)

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

### Antigravity

```bash
agentpack install --agent antigravity
```

Configures:
- `.agent/skills/agentpack/SKILL.md` — AgentPack context as a Skill; Antigravity activates it automatically for coding tasks
- `GEMINI.md` — registers the agentpack skill reference
- `.git/hooks/post-commit`, `post-merge`, `post-checkout` — background repack on tree change
- `.vscode/tasks.json` — "AgentPack: Repack context" in Command Palette + `runOn: folderOpen`

The Skill descriptor activates AgentPack automatically — no `--task` flag required when working in Antigravity.

### Auto-repack comparison

| Mechanism | Claude Code | Cursor | Windsurf | Codex | Antigravity |
|---|---|---|---|---|---|
| Config file patched | `CLAUDE.md` + `.claude/settings.json` | `.cursorrules` + `.cursor/rules/*.mdc` | `.windsurfrules` | `AGENTS.md` | `.agent/skills/agentpack/SKILL.md` + `GEMINI.md` |
| Auto-inject on startup | ✅ `UserPromptSubmit` hook | ✅ `alwaysApply` | ✅ rules file | ✅ `AGENTS.md` | ✅ Skill auto-activation |
| Auto-repack when stale | ✅ hook (content hash via `root_hash`, ~1ms when fresh) | ✅ git hooks | ✅ git hooks | ✅ git hooks | ✅ git hooks |
| Manual repack shortcut | ✅ `/agentpack` slash cmd | ✅ VS Code task | ✅ VS Code task | `agentpack pack` | ✅ VS Code task |

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

### agentpack's own CI

agentpack uses two workflows:

- **`ci.yml`** — runs tests (Python 3.10–3.13) + ruff lint + 80% coverage gate on every push and PR to `main`
- **`publish.yml`** — runs on every `v*` tag push; requires tag from a `release/*` branch and a CHANGELOG.md entry for the version before building and publishing to PyPI (trusted publishing)

### Add context packing to your repo

Add to `.github/workflows/agentpack-context.yml`:

```yaml
name: AgentPack context pack

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

      - run: pip install agentpack-cli

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

Reviewers download the artifact and open it in their agent of choice. No repo clone needed — the pack contains full content for changed files and summaries for dependencies.

---

## Commands

### `agentpack global-install`

Install once — works in every repo from that point on. The recommended first step.

```bash
agentpack global-install                       # auto-detect IDE
agentpack global-install --agent claude        # Claude Code
agentpack global-install --agent cursor        # Cursor
agentpack global-install --agent windsurf      # Windsurf
agentpack global-install --agent codex         # Codex
agentpack global-install --agent antigravity   # Antigravity
```

What it does:
- **Git template hooks** (`~/.git-templates/hooks/`) — git copies these into every repo on `git init` / `git clone`. On `post-commit`, `post-merge`, `post-checkout`: silently repacks **only if `.agentpack/config.toml` exists** — no-op in repos that haven't opted in.
- **Shell cd hook** (`~/.zshrc` or `~/.bashrc`) — on `cd`, repacks if stale **only in opted-in repos**. Never touches repos without `.agentpack/config.toml`. Never auto-inits.
- **Agent config** — same as `agentpack install --agent <x>` for the current project.

All changes are idempotent, reversible, and non-destructive. Existing hooks and rc files are appended to, never overwritten. Repos you haven't explicitly run `agentpack init` in are never touched.

Options:

| Flag | Default | Description |
|---|---|---|
| `--agent` | `auto` | Target agent (`auto` \| `claude` \| `cursor` \| `windsurf` \| `codex` \| `antigravity`) |
| `--no-pipx` | — | Skip pipx install (if agentpack already installed) |
| `--no-shell-hook` | — | Skip shell rc patching |
| `--no-git-template` | — | Skip git template hooks |
| `--dry-run` | off | Show what would be changed without touching anything |

Preview before committing:

```bash
agentpack global-install --dry-run
```

---

### `agentpack global-uninstall`

Remove all global hooks — git templates and shell rc. Per-project `.agentpack/` directories are untouched.

```bash
agentpack global-uninstall
agentpack global-uninstall --no-shell-hook    # remove only git template hooks
agentpack global-uninstall --no-git-template  # remove only shell hook
```

---

### `agentpack doctor`

Diagnose your agentpack installation — checks CLI, git template hooks, git config, shell hook, per-repo state, and agent config.

```bash
agentpack doctor
```

Example output:

```
CLI
  ✓ agentpack found at /usr/local/bin/agentpack (0.1.0)

Git template hooks (~/.git-templates/hooks/)
  ✓ post-commit
  ✓ post-merge
  ✓ post-checkout

git config init.templateDir
  ✓ init.templateDir = /Users/you/.git-templates

Shell cd hook
  ✓ Hook present in /Users/you/.zshrc

Per-repo state
  ✓ .agentpack/config.toml present
  ✓ context pack present (age: 2m)

Agent config
  ✓ CLAUDE.md (agentpack configured)
  - .cursorrules not present (optional)
  ✓ Claude hooks present (local): .claude/settings.json
  ! ~/.claude/settings.json has no agentpack hooks — run: agentpack install --agent claude --global
  ! Hooks local-only — context won't auto-inject in other repos. Run: agentpack install --agent claude --global

Slash command (/agentpack)
  ✓ Slash command installed (local): .claude/commands/agentpack.md
  - Slash command not installed globally — run: agentpack install --agent claude --global

Some checks failed. Run the suggested commands above to fix.
```

The new checks in `doctor`:
- **Local vs global hooks**: warns when Claude hooks are only in the per-project `.claude/settings.json` — context won't auto-inject in other repos
- **Slash command presence**: checks both local (`.claude/commands/`) and global (`~/.claude/commands/`) installations
- **Source checkout mismatch**: warns when you're inside an AgentPack source checkout but the `agentpack` executable imports the installed site-packages copy. Use `PYTHONPATH=src python -m agentpack.cli ...` or `pip install -e .` for local development.

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
agentpack install                      # auto-detect IDE
agentpack install --agent claude       # CLAUDE.md + .claude/settings.json hooks
agentpack install --agent cursor       # .cursorrules + .mdc + git hooks + VS Code tasks
agentpack install --agent windsurf     # .windsurfrules + git hooks + VS Code tasks
agentpack install --agent codex        # AGENTS.md + git hooks
agentpack install --agent antigravity  # .agent/skills/agentpack/SKILL.md + GEMINI.md + git hooks + VS Code tasks
```

All installs are idempotent — safe to re-run, merge with existing config, never duplicate.

---

### `agentpack summarize`

Build or refresh the offline summary cache. **No API calls, ever.**

```bash
agentpack summarize              # build summaries for all files not yet cached
agentpack summarize --refresh    # force rebuild all
```

Summaries are built with parallel AST/regex analysis — no network, no tokens spent. Run once after `init`. After that, pack automatically rebuilds summaries only for changed files (hash-keyed cache).

---

### `agentpack pack`

Generate a context pack.

```bash
agentpack pack --task "fix auth session bug"        # auto-detects your IDE
agentpack pack --agent claude --task "fix auth bug" # explicit agent

# Only include changes since a git ref
agentpack pack --task "review these changes" --since main

# Watch mode — re-packs on every file change
agentpack pack --task "refactor auth" --session
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--agent` | `auto` | Target agent (`auto` \| `claude` \| `cursor` \| `windsurf` \| `codex` \| `antigravity` \| `generic`). `auto` detects the active IDE from env and project files. |
| `--task` | `auto` | Task description, or `auto` to infer from git |
| `--mode` | `balanced` | Budget mode: `minimal`, `balanced`, `deep` |
| `--budget` | 0 (uses config default 25000) | Token budget |
| `--since` | — | Only include files changed since this git ref |
| `--session` | off | Re-pack on every file change (watch mode) |
| `--refresh` | off | Force rebuild summaries before packing |

**Budget modes:**

| Mode | What's included |
|------|----------------|
| `minimal` | Changed files + direct configs, with a small summary cap |
| `balanced` | Changed files + deps + reverse deps + tests + capped summaries |
| `deep` | Everything in balanced + docs + more full-content files, uncapped summaries |

`pack` also prints diagnostics when the pack looks noisy: very short task text, no changed files, mostly filename matches, mostly summaries, many symbol matches, weak summaries excluded by the score floor, or summaries excluded by the mode cap.

---

### `agentpack quickstart`

Show the shortest useful path for the current repo.

```bash
agentpack quickstart
agentpack quickstart --task "fix auth token expiry"
agentpack quickstart --task "fix auth token expiry" --write
```

`quickstart` does not guess at magic. It checks whether `.agentpack/config.toml`, `.agentpack/task.md`, and context packs exist, then prints the next few commands. With `--write`, it writes the supplied task into `.agentpack/task.md`.

---

### `agentpack session` _(removed)_

Session management was removed in v0.1.12. `agentpack init` bootstraps the session automatically. Use `agentpack watch` to keep context current. To change the task, edit `.agentpack/task.md`.

---

### `agentpack watch`

Watch for file and task changes, refresh context automatically.

```bash
agentpack watch                        # uses session agent/mode if session active
agentpack watch --debounce 3.0         # wait 3s after last change before refresh
```

Uses `watchdog` if installed, falls back to polling. Context is refreshed whenever source files or `.agentpack/task.md` change.

Install watchdog for better performance:
```bash
pip install "agentpack-cli[watch]"
```

---

### `agentpack claude`

Launch Claude CLI with an up-to-date context.

```bash
agentpack claude
```

Requires an initialized project (`agentpack init`). Refreshes context, prints the context path, then launches `claude` if found. Transparent about what it does — no fake prompt injection.

---

### `agentpack mcp`

Run AgentPack as an MCP server — exposes context packing as tools that Claude Code (and any MCP-compatible agent) can call directly.

```bash
pip install "agentpack-cli[mcp]"
agentpack mcp
```

Register in Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "agentpack": {
      "command": "agentpack",
      "args": ["mcp"]
    }
  }
}
```

**Tools exposed:**

| Tool | Description |
|---|---|
| `pack_context(task, mode, budget, max_tokens)` | Generate a ranked context pack for a task. Returns packed markdown, truncated to `max_tokens` (default 20,000). |
| `get_context()` | Return the latest pre-built pack instantly (no repack). Prepends a freshness/staleness header so you know if it's stale. |
| `refresh()` | Refresh using the current `task.md` or git-inferred task. |

**Staleness detection:** `get_context()` compares the snapshot hash from when the pack was built against the current repo snapshot. If files changed since last pack, it prepends:
```
> **Stale context** — repo changed since last pack (generated: ...). Run pack_context() to refresh.
```

**Smart truncation:** `pack_context()` keeps headers intact and trims file content blocks to fit the token budget, appending a note about how many files were omitted.

Zero API calls — all analysis is offline. Summary cache keyed by file hash: cold run parallelises AST parsing across CPU cores; warm cache hits are instant.

---

### `agentpack explain`

Debug file selection — show which files would be selected, why, and what was excluded — without writing a context pack.

```bash
agentpack explain --task "fix auth session bug"
agentpack explain --task auto
agentpack explain --file src/auth/session.py   # per-file score breakdown
agentpack explain --omitted                    # top-10 excluded files
```

Per-file breakdown (`--file`):

```
src/auth/session.py
  selected:  yes
  score:     310
  include:   full
  tokens:    4,200

  signals:
    +100  modified
    +80   filename keyword match
    +60   content keyword match (6)
    +50   direct dependency of changed file
    +35   has related tests

  symbols: create_session, revoke_session, validate_session
```

Use `--omitted` to see what was left out and why. Use `--file` when a file you expected isn't showing up.

---

### `agentpack benchmark`

Measure token efficiency, file selection quality, and speed across tasks.

```bash
agentpack benchmark --task "fix auth token expiry"         # single task
agentpack benchmark --task "fix auth bug" --compare        # compare minimal/balanced/deep
agentpack benchmark --init                                 # scaffold .agentpack/benchmark.toml
agentpack benchmark                                        # run all cases in benchmark.toml
agentpack benchmark --sample-fixtures                      # source checkout demo evals
agentpack benchmark --misses                               # explain expected-file misses
```

Output per case:

```
fix auth token expiry  mode=balanced

   packed tokens     29,357
   raw tokens       187,998
   saving             84.4%
   files selected       234
   changed covered    2/2  (100%)
   total time          0.45s

   phase    time
   scan     0.257s
   rank     0.027s
   select   0.009s

  top files: src/auth/token.py, src/auth/session.py, ...
```

**Compare mode** shows all three modes side-by-side:

```
Mode comparison: fix auth token expiry

   mode        tokens   saving   files   time
   minimal     29,882    84.1%     253   0.34s
   balanced    29,882    84.1%     253   0.24s
   deep         7,563    96.0%      43   0.24s
```

**With expected files** (add to `benchmark.toml`), you get precision/recall/F1:

```toml
[[cases]]
task = "fix auth token expiry"
mode = "balanced"
task_type = "backend-api"
expected_files = [
  "src/auth/token.py",
  "src/auth/session.py",
]
```

```
  precision 100.0%  recall 100.0%  F1 100.0%
  hit: src/auth/session.py, src/auth/token.py
```

Use `--misses` when recall is low. It prints each expected file that was not selected with status, rank, score, and scoring reasons, which helps separate ignored files, budget cuts, low scores, and missing dependency signals.

Add `task_type` to group results by workflow area. Benchmark summaries report average precision, recall, F1, and token noise by type, so a repo can show "backend-api is good, frontend-web is noisy" instead of hiding that under one aggregate.

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

Show session state, token statistics, and selection accuracy for the last pack.

```bash
agentpack stats
```

When a session is active, shows session panel (agent, mode, started, refresh count) above token stats. Also lists top included files from the latest pack and avg recall/precision/F1 over the last 10 runs.

Newer metrics include token-weighted precision. File precision answers "how many selected files were later changed"; token precision answers "how many selected tokens were spent on files later changed." `stats` also breaks token precision down by inclusion mode (`full`, `symbols`, `summary`) so summary noise is visible.

To build a real usefulness signal for your repo:

```bash
agentpack benchmark --sample-fixtures

agentpack benchmark --init
# edit .agentpack/benchmark.toml with real tasks + files you actually changed
agentpack benchmark --compare --misses
```

`--sample-fixtures` runs bundled FastAPI, Next.js, and mixed Python/TypeScript fixture evals from an AgentPack source checkout. It is a smoke test, not a claim about your repo.

For an 8+ usefulness signal, use `benchmark.toml` with real third-party or customer-style repos: 5-20 historical tasks, `task_type` labels, the files actually changed for each task, and `--compare` results for recall, F1, rank@K, and token noise. That is better than trusting generic benchmarks because it tells you whether AgentPack selects the files that matter in code the package has never seen.

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
| Knowledge/architecture doc (DECISIONS.md, ADR-*.md, ARCHITECTURE.md, docs/adr/, docs/decisions/, docs/rfcs/) | +30 |
| Config file | +25 |
| Recently modified | +20 |
| High churn (top 10% by commit frequency) | +15 |
| Large unrelated file | −50 |
| Ignored/binary | −100 |

Keyword scoring uses weighted concept synonym expansion — literal task terms are strongest, normalized variants are slightly weaker, and broad concept synonyms are weaker again. "rate limiting" still expands to `throttle`, `leaky`, `bucket`, `quota`, but broad expansions no longer dominate literal task terms. Matching is token-based, so `task` does not accidentally match every `tasks.py`.

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
min_summary_score = 60
max_summary_files_minimal = 15
max_summary_files_balanced = 40
max_summary_files_deep = 0
include_tests = true
include_configs = true
include_receipts = true

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
knowledge_file            = 30   # DECISIONS.md, ADR-*.md, ARCHITECTURE.md, docs/adr/ etc.
config_file               = 25
recently_modified         = 20
churn_high                = 15   # top 10% by commit frequency
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
          │  Symbol extract  ── Python AST (full)   │
          │    (body via       ── JS/TS (functions, │
          │  ast.get_source_segment)   classes,     │
          │                    ── arrow fns w/ =>)  │
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
          │  Claude adapter      ──▶  context.claude.md │
          │  Cursor adapter      ──▶  context.md        │
          │  Windsurf adapter    ──▶  context.md        │
          │  Codex adapter       ──▶  context.md        │
          │  Antigravity adapter ──▶  .agent/skills/agentpack/SKILL.md │
          │  Generic adapter     ──▶  context.md        │
          │                                         │
          │  Context receipts (why each file in/out)│
          │  Secret redaction (AWS/GH/OpenAI tokens)│
          └─────────────────────────────────────────┘
```

### Package layout

```
src/agentpack/
  cli.py                       # Typer CLI entry point (thin — delegates to commands/)

  data/
    agentpack.md               # bundled /agentpack slash command for Claude CLI

  application/
    pack_service.py            # PackPlanner: shared scan→rank→select pipeline
                               # PackService: materializes plan → writes context file
                               # AdapterRegistry: maps agent names to adapter instances
                               # PackRequest / PackResult / PackPlan DTOs

  domain/  (via core/models.py)
    FileInfo, ScanResult       # scan output (packable / ignored / binary)
    Symbol, FileSummary        # summary cache objects
    SelectedFile, Receipt      # selection output with redaction_warnings
    ContextPack                # final artifact with redaction_warnings
    DependencyNode             # typed graph node (path, imports, imported_by, tests)
    DependencyGraph            # typed graph container (nodes dict + dict-like accessors)

  core/
    models.py                  # Pydantic domain models (see above)
    config.py                  # TOML config + ScoringWeights
    ignore.py                  # .agentignore / gitignore-style matching
    scanner.py                 # rglob → ScanResult (packable/ignored/binary split)
    snapshot.py                # JSON snapshots + merkle root hash
    diff.py                    # added / modified / deleted / unchanged diff
    git.py                     # subprocess git + task inference from branch/commits
    merkle.py                  # root hash: sort(path:hash) → sha256
    cache.py                   # summary cache keyed path+hash+provider+version
    context_pack.py            # select_files: budget selection + secret redaction
    token_estimator.py         # tiktoken cl100k_base (approximate)
    redactor.py                # redact_secrets: fires at content materialization
    bootstrap.py               # is_initialized, bootstrap_if_needed

  analysis/
    dependency_graph.py        # build(): returns typed DependencyGraph over packable files
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
    base.py                    # cache-or-build orchestration (parallel, ThreadPool+ProcessPool)

  adapters/                    # context rendering only — no installation logic
    base.py                    # abstract BaseAdapter (output_path + render + write)
    claude.py                  # renders context.claude.md via render_claude()
    cursor.py                  # renders context.md via render_generic()
    windsurf.py                # renders context.md
    codex.py                   # renders context.md
    antigravity.py             # renders .agent/skills/agentpack/SKILL.md (SKILL.md frontmatter + body)
    generic.py                 # renders context.md (any LLM)
    detect.py                  # detect_agent(): infers active IDE from env vars + project files

  installers/                  # repo/tool configuration — separate from rendering
    claude.py                  # ClaudeInstaller: CLAUDE.md + .claude/settings.json
    cursor.py                  # CursorInstaller: .cursorrules + .mdc + auto-repack
    windsurf.py                # WindsurfInstaller: .windsurfrules + auto-repack
    codex.py                   # CodexInstaller: AGENTS.md + git hooks
    antigravity.py             # AntigravityInstaller: GEMINI.md + .agent/skills/ + auto-repack

  integrations/                # system/tool integration (not core domain)
    git_hooks.py               # install/remove .git/hooks post-commit/merge/checkout
    vscode_tasks.py            # install/remove .vscode/tasks.json entries
    global_install.py          # global: git template hooks + shell rc hook

  renderers/
    markdown.py                # renders pre-redacted ContextPack to markdown
    compact.py                 # compact protocol format for session context files
    receipts.py                # context receipt formatter

  session/
    state.py                   # SessionState dataclass + load/save/create/stop helpers
    __init__.py                # re-exports from state.py

  commands/                    # CLI only — parse args, call services/installers
    pack.py                    # agentpack pack → PackService.run()
    install.py                 # agentpack install / global-install → installers/
    init.py                    # agentpack init
    quickstart.py              # agentpack quickstart — guided first-run commands
    scan.py                    # agentpack scan
    diff.py                    # agentpack diff
    status.py                  # agentpack status
    stats.py                   # agentpack stats
    summarize.py               # agentpack summarize
    monitor.py                 # agentpack monitor
    explain.py                 # agentpack explain
    doctor.py                  # agentpack doctor
    hook_cmd.py                # agentpack hook — Claude prompt hook + stale detection
    mcp_cmd.py                 # agentpack mcp — MCP server entrypoint
    watch.py                   # agentpack watch — file watcher with debounce
    claude_cmd.py              # agentpack claude — refresh + launch claude
    benchmark.py               # agentpack benchmark — token efficiency, recall, miss diagnostics
```

### Key architectural properties

- **Redaction at materialization**: secrets are stripped inside `select_files()` before content reaches any renderer or adapter. Every output format gets redacted content automatically — no per-renderer redaction needed.
- **`ScanResult` splits cleanly**: `scan()` returns `ScanResult(packable, ignored, binary)` — downstream code only processes `packable` files, eliminating `if f.ignored or f.binary` guards throughout.
- **`PackPlanner` owns shared planning**: `PackPlanner.plan()` runs scan → summarize → graph → rank → select and returns a `PackPlan`. Both `pack` and `explain` use the same planner — no duplicated pipeline logic, no drift.
- **`PackService` materializes a plan**: takes a `PackPlan`, builds the `ContextPack` artifact, delegates rendering to `AdapterRegistry`, persists snapshot + metadata + metrics.
- **`AdapterRegistry` maps agent → adapter**: adding a new agent output format requires one entry in `AdapterRegistry.get()`, not changes to `PackService`.
- **`detect_agent()` runs at invocation time**: `--agent auto` (the default) calls `detect_agent()` fresh on every `pack` run and git hook execution — so context is always written for the active IDE, even when switching between agents or running in CI.
- **`DependencyGraph` is typed**: `dependency_graph.build()` returns `DependencyGraph(nodes: dict[str, DependencyNode])` — no more `dict[str, dict]` with stringly-typed keys like `"imported_by"`. Typos are caught at the model layer.
- **`integrations/` vs `core/`**: git hooks, shell rc patching, and VS Code tasks are infrastructure concerns — they live in `integrations/`, not `core/`. `core/` is pure domain logic.
- **Adapters render; installers configure**: `adapters/` knows how to write a context file for an agent. `installers/` knows how to configure the agent's tool (CLAUDE.md, .cursorrules, settings.json). They are separate concerns and separate classes.

---

## Practical examples

### Bug fix: "I have a failing test, help me fix it"

```bash
# You're debugging a test failure in the auth module
agentpack pack --task "fix failing test in auth token validation"
```

AgentPack selects: the failing test file (modified), `auth/token.py` (dep), `auth/session.py` (dep), `config/settings.py` (config), skips 180 unrelated files. Your agent gets 12k tokens of precisely relevant context and starts debugging immediately.

---

### Feature: "Add rate limiting to the API"

```bash
# On a feature branch, nothing modified yet
agentpack pack --task "add rate limiting to REST API endpoints"
```

Keyword expansion activates: "rate limiting" → `throttle`, `leaky`, `bucket`, `quota`. AgentPack scores: `middleware/` directory (path keyword `api`), existing `throttle.py` or `leaky_bucket.py` (content keyword), `routes/*.py` (deps). Your agent gets the full middleware stack and starts implementing, not exploring.

---

### Code review: "Review my PR before I push"

```bash
# Review only what changed vs main
agentpack pack --task "code review auth refactor" --since main
```

Only files touched in this branch are included (full content). Everything else is summaries or omitted. Your agent reviews exactly the diff-visible code, not the whole codebase.

---

### Refactor: "Help me refactor the database layer"

```bash
agentpack pack --task "refactor database connection pooling" --mode deep
```

`--mode deep` adds: related docs, more full-content files, broader dep tree. Use when the task touches many files and you want your agent to see more context upfront.

---

### CI: automated context on every PR

Add to `.github/workflows/agentpack-context.yml` — see the full example in [CI/CD: pack per PR](#cicd-pack-per-pr). Reviewers and CI bots get focused context without cloning the repo.

---

### Session mode: keep context fresh while you work

```bash
# One-time project setup
agentpack init                     # creates config, session, task.md
# Edit .agentpack/task.md to set your task

# Every terminal session — just one command
agentpack watch                    # keeps context fresh automatically

# Change task mid-session: edit .agentpack/task.md directly
# watch detects the change and refreshes automatically
```

---

### Debug why a file isn't showing up

```bash
agentpack explain --task "fix rate limiting in auth middleware"
# Top selected files:
#   1. src/auth/middleware.py  score=180  [full]     modified, filename keyword match
#   2. src/auth/limiter.py     score=130  [symbols]  dep + content keyword "throttle"
#   ...
# Excluded:
#   - src/payments/billing.py  score=8    score too low
```

---

## Tips & tricks

### Let `--task auto` do the work

Skip writing a task description — agentpack infers it from your branch name, changed files, and recent commits:

```bash
agentpack pack --task auto
```

Priority order (strongest → weakest):

| Source | Example output |
|--------|---------------|
| `task.md` (explicit) | `"migrate DB schema to multi-tenant"` |
| branch + staged files | `"feat add-rate-limiting: payments, throttle"` |
| staged files only | `"payments, throttle"` |
| branch + unstaged | `"feat add-rate-limiting: session, token"` |
| branch + latest commit | `"feat add-rate-limiting: fix token expiry check"` |
| branch name alone | `"feat add-rate-limiting"` |
| unstaged files | `"session, token"` |
| recent commit messages | `"fix token expiry check; add pagination"` |
| recently modified files | `"session, payments"` (noisy — last resort) |

The heuristic that fired is logged: `Auto task (branch+staged): feat add-rate-limiting: payments`.

The more descriptive your branch names (`feat/add-rate-limiting` beats `dev`) and the more you stage before running, the more accurate the inference.

### Concept synonym expansion

AgentPack expands task keywords automatically — "rate limiting" expands to `throttle`, `leaky`, `bucket`, `quota`, `debounce`; "auth" expands to `jwt`, `bearer`, `token`, `oauth`; "cache" expands to `lru`, `memoize`, `redis`, `ttl`; domain terms such as `kundali` expand toward astrology/chart/compatibility terms. Files that implement a concept but don't use its exact name can still rank.

### Full-stack role boosts

When a task points at a page, route, or API surface, AgentPack also gives a controlled boost to related implementation roles such as `service`, `controller`, `schema`, `handler`, `repository`, and `client`. This helps full-stack tasks pull backend implementation files instead of only frontend entrypoints.

This is still heuristic. If a service should have appeared and did not, add it as an `expected_files` entry in `benchmark.toml` and run:

```bash
agentpack benchmark --compare --misses
```

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
agentpack pack --task "review auth changes" --since main
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
agentpack init                  # one-time setup (creates session + task.md)
agentpack watch                 # in another terminal — auto-resumes each time
```

Refreshes `.agentpack/context.md` every time you save a file. Change the task by editing `.agentpack/task.md` directly — or tell Claude and it writes the file itself. `watch` picks up the change automatically.

### Debug file selection with `explain`

```bash
agentpack explain --task "fix auth session bug"
```

Shows ranked scores and reasons before committing to a pack. Use when a file you expect isn't appearing.

For repeatable evals, prefer `benchmark --misses` because it compares selected files against the files you actually changed for historical tasks.

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

- **Local-first**: `init`, `scan`, `diff`, `pack`, `stats`, `summarize` make zero API calls — ever. No optional LLM paths, no per-file costs.
- **Non-destructive**: never overwrites user files; config patching only touches agentpack-managed blocks
- **Agent-neutral**: architecture is generic; Claude Code is the primary target (deepest integration); Cursor, Windsurf, Codex, and Antigravity are supported but less battle-tested
- **No daemons**: file watching is opt-in via `agentpack watch`; git hooks run in the background and are opt-in via `install`
- **Measurable**: `benchmark`, `stats`, receipts, and `--misses` are first-class because compression without recall is not enough
- **Honest**: packed token count reflects real content, and raw-repo savings are presented separately from practical usefulness

---

## Known limitations

- **Windows**: not supported. Git hooks use POSIX shell (`#!/bin/sh`, `>/dev/null 2>&1 &`). The Claude Code session hooks use `python3` and `rm -f`. Contributions welcome.
- **Monorepos**: single-root repos only. If you `agentpack pack` from a monorepo root, all packages are scanned together with no workspace awareness. Workaround: `cd packages/my-pkg && agentpack init && agentpack pack`.
- **Symbol extraction**: Python (AST, full) and JavaScript/TypeScript (regex, arrow functions + classes) are well-supported. Go, Rust, Java, Kotlin have import graph traversal but no symbol extraction — they fall back to file-level summaries.
- **Selection recall**: ranking is heuristic. It can miss files when task language differs from code language, when repos have unusual architecture, or when important files are only connected at runtime.
- **Secret redaction**: covers AWS keys, GitHub tokens, OpenAI/Anthropic keys, JWTs, and private key blocks. Not a substitute for a dedicated secrets scanner on sensitive repos.
- **Token estimates**: uses tiktoken `cl100k_base` — approximate, not exact for Claude's billing.
- **Large repos (>5k files)**: global auto-bootstrap is skipped for repos over 5,000 files to avoid hangs. Run `agentpack init` explicitly in large codebases.

---

## Optional dependencies

```bash
pip install "agentpack-cli[watch]"    # watchdog — faster file watching for agentpack watch
pip install "agentpack-cli[mcp]"      # mcp — expose agentpack as MCP server tools
pip install "agentpack-cli[all]"      # watch + mcp
```

---

## Development

Clone and run locally:

```bash
git clone https://github.com/vishal2612200/agentpack.git
cd agentpack
python -m pip install -e ".[dev,watch,mcp]" build
pytest
```

Useful checks before opening a PR:

```bash
pytest
python -m ruff check src tests
python -m build
npm test --prefix npm
(cd npm && npm pack --dry-run)
agentpack benchmark --sample-fixtures --misses
```

Good contribution areas:

- More real-world benchmark fixtures and public repo eval cases
- Windows support for hooks and session integrations
- Better symbol extraction for Go, Rust, Java, and Kotlin
- More precise import/dependency resolution for framework-heavy repos
- Ranking regressions with `expected_files` cases that reproduce misses
- npm wrapper improvements that preserve the Python CLI as the source of truth

Please include tests for ranking changes. A good ranking PR usually adds one focused unit test and one scenario in `tests/test_ranking_evals.py`.

---

## License

MIT
