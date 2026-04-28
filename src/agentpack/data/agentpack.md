---
description: Pack repo context and immediately start working on the task. Runs agentpack init + pack, reads the context, and begins helping — no manual piping needed.
---

# AgentPack

Pack the repo context and immediately start working on the task.

## Usage

```
/agentpack --task "fix Redis SSE cancellation issue"
/agentpack --task "add rate limiting to auth endpoints" --mode deep
/agentpack init
/agentpack status
/agentpack stats
/agentpack diff
/agentpack summarize
/agentpack install
```

## Process

### Step 1: Check agentpack is installed

```bash
agentpack --version 2>/dev/null || pip install agentpack
```

### Step 2: Initialize if not already done

```bash
test -f .agentpack/config.toml || agentpack init
```

### Step 3: Determine the task

- If `--task "..."` provided → use it exactly
- Otherwise → run `git log --oneline -5` and infer from recent commits, confirm in one sentence

### Step 4: Run pack

```bash
agentpack pack --agent claude --task "<task>" --mode balanced
```

### Step 5: Read the context pack

Read `.agentpack/context.claude.md` in full. Do NOT ask the user to pipe it.

### Step 6: Immediately start working

Using the context you just read:

1. **Orient** — state which files are changed and what the key code areas are (2-3 sentences)
2. **Diagnose or plan** — root cause for bugs, approach for features. Reference specific file:line
3. **Start working** — edit code, fix the issue, implement the feature

Do not say "context pack ready" and stop. Do not tell the user to run more commands.

## Stale pack handling

If pack is stale, re-run automatically before reading context.

## Subcommand routing

| User types | Action |
|---|---|
| `/agentpack --task "..."` | init + pack + read + work |
| `/agentpack` | init + pack (ask for task if none) |
| `/agentpack init` | `agentpack init` only |
| `/agentpack status` | check staleness |
| `/agentpack stats` | token savings |
| `/agentpack diff` | changed files |
| `/agentpack summarize` | rebuild summaries |
| `/agentpack install` | `agentpack install --agent claude` |

## Notes

- All pack/scan/diff are local — no API calls
- Changed files are highest priority in context
- Never overwrite `.agentignore` or `config.toml` without `--force`
