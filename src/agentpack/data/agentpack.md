---
description: Pack repo context and immediately start working on the task. Supports session mode (start once, work normally) and manual pack mode. Reads context and begins helping — no manual piping needed.
---

# AgentPack

Pack repo context and immediately start working on the task.

## Usage

```
/agentpack --task "fix Redis SSE cancellation issue"
/agentpack --task "add rate limiting to auth endpoints" --mode deep
/agentpack --task auto      # infer task from branch + changed files + git log
/agentpack init             # interactive: prompts for default mode
/agentpack status
/agentpack stats
/agentpack diff
/agentpack summarize
/agentpack install
/agentpack session start
/agentpack session status
/agentpack session refresh --task "new task"
/agentpack session stop
/agentpack watch
/agentpack claude
/agentpack explain --task auto
/agentpack explain --file src/auth/session.py
/agentpack explain --omitted
```

## Session Mode (recommended)

If a session is already running (`.agentpack/session.json` exists and `"active": true`):

1. Read `.agentpack/context.md` — context is already fresh.
2. If the user gives a new coding task, write a one-line summary to `.agentpack/task.md`.
3. Re-read `.agentpack/context.md` after watch mode refreshes it (a few seconds).
4. Proceed with the task using the context you just read.

To start a session:

```bash
agentpack session start                     # creates session + generates initial context
agentpack session start --agent claude      # specify agent
agentpack session start --task "fix bug"    # set initial task

agentpack watch                             # in another terminal — auto-refreshes on changes
```

To check session state:

```bash
agentpack session status    # shows active, agent, mode, last refresh, refresh count
agentpack stats             # shows session panel + token stats + top files
```

To force a refresh:

```bash
agentpack session refresh
agentpack session refresh --task "new task description"
```

To stop:

```bash
agentpack session stop
```

Then use normal prompts — context stays current while `watch` is running.

## Manual Pack Mode (no session)

```bash
agentpack pack --agent claude --task "<task>" --mode balanced
```

Then read `.agentpack/context.claude.md` in full.

## Process

### Step 1: Check agentpack is installed

```bash
agentpack --help 2>/dev/null || pip install agentpack-cli
```

### Step 2: Initialize if not already done

```bash
test -f .agentpack/config.toml || agentpack init --yes
```

### Step 3: Determine workflow

**Session active** (`.agentpack/session.json` exists, `"active": true`):
- Read `.agentpack/context.md`
- Update `.agentpack/task.md` if task changed
- Proceed immediately

**No session**:
- Run `agentpack session start` or `agentpack pack --task auto`
- Read the context file
- Proceed

### Step 4: Immediately start working

Using the context you just read:

1. **Orient** — state which files are changed and what the key code areas are (2-3 sentences)
2. **Diagnose or plan** — root cause for bugs, approach for features. Reference specific file:line
3. **Start working** — edit code, fix the issue, implement the feature

Do not say "context pack ready" and stop. Do not tell the user to run more commands.

## Stale pack handling

If `agentpack status` exits non-zero or context seems unrelated to the task:
- Run `agentpack session refresh` (if session active)
- Or run `agentpack pack --task auto` (manual mode)
- Re-read the context, then proceed

Do not ask the user — just refresh and proceed.

## Debugging selection

```bash
agentpack explain --task auto                          # show ranked file list
agentpack explain --file src/auth/session.py           # per-file score breakdown
agentpack explain --omitted                            # see what was excluded and why
```

## Subcommand routing

| User types | Action |
|---|---|
| `/agentpack --task "..."` | check session or pack + read + work |
| `/agentpack` | check session or pack with `--task auto` + read + work |
| `/agentpack session start` | `agentpack session start` |
| `/agentpack session status` | `agentpack session status` |
| `/agentpack session refresh` | `agentpack session refresh` |
| `/agentpack session stop` | `agentpack session stop` |
| `/agentpack watch` | `agentpack watch` (foreground, Ctrl+C to stop) |
| `/agentpack claude` | `agentpack claude` (refresh + launch claude) |
| `/agentpack init` | `agentpack init` only |
| `/agentpack status` | check staleness |
| `/agentpack stats` | session info + token savings |
| `/agentpack diff` | changed files |
| `/agentpack summarize` | rebuild offline summary cache |
| `/agentpack install` | `agentpack install --agent claude` |
| `/agentpack explain` | show ranked file selection |

## Notes

- All commands are local — no API calls
- `--task auto` infers from branch name → changed file paths → recent commit
- Changed files are highest priority in context
- Session context files: `.agentpack/context.md` (readable), `.agentpack/context.compact.md` (compact)
- Never overwrite `.agentignore` or `config.toml` without `--force`
