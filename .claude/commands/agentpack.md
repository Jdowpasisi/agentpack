---
description: Pack repo context and immediately start working on the task. Runs agentpack init + pack, reads the context, and begins helping — no manual piping needed.
---

# AgentPack

Pack the repo context and immediately start working on the task.

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
```

## Process

### Step 1: Check agentpack is installed

```bash
agentpack --version 2>/dev/null || pip install agentpack
```

### Step 2: Initialize if not already done

```bash
test -f .agentpack/config.toml || agentpack init --yes
```

### Step 3: Determine the task

- If `--task "..."` provided → use it exactly
- If `--task auto` or no `--task` → run `agentpack pack --task auto` (infers from branch + changed files + recent commit)

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

If `agentpack status` exits non-zero, re-run pack before reading context. Do not ask the user — just re-pack and proceed.

## Subcommand routing

| User types | Action |
|---|---|
| `/agentpack --task "..."` | init + pack + read + work |
| `/agentpack` | init + pack with `--task auto` + read + work |
| `/agentpack init` | `agentpack init` only |
| `/agentpack status` | check staleness |
| `/agentpack stats` | token savings |
| `/agentpack diff` | changed files |
| `/agentpack summarize` | rebuild offline summary cache |
| `/agentpack install` | `agentpack install --agent claude` |

## Notes

- All pack/scan/diff are local — no API calls
- `--task auto` infers from branch name → changed file paths → recent commit (in priority order)
- Changed files are highest priority in context
- Never overwrite `.agentignore` or `config.toml` without `--force`
