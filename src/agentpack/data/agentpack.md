---
description: Initialize AgentPack in the current repo and generate a compact context pack for Claude CLI.
---

# AgentPack

Initialize AgentPack in the current repo and generate a token-efficient context pack focused on your task.

## Usage

```
/agentpack                          # init (if needed) + pack with balanced mode
/agentpack --task "fix auth bug"    # init + pack with specific task
/agentpack init                     # initialize only
/agentpack pack --task "..." --mode minimal|balanced|deep
/agentpack status                   # check if pack is stale
/agentpack stats                    # show token savings
/agentpack diff                     # show changes since last snapshot
/agentpack summarize                # rebuild offline summary cache
```

## Process

### Step 1: Check agentpack is installed

Run:
```bash
agentpack --version 2>/dev/null || pip install agentpack
```

If not installed, install it first.

### Step 2: Initialize if not already done

Check for `.agentpack/config.toml`:
- Missing → run `agentpack init`
- Present → skip

### Step 3: Determine the task

- If `--task "..."` provided → use it directly
- Otherwise → check recent git log (`git log --oneline -5`) to infer context, or ask user for a one-line task description

### Step 4: Generate the context pack

```bash
agentpack pack --agent claude --task "<task>" --mode balanced
```

### Step 5: Report and guide usage

Show the result summary:
```
Context pack ready: .agentpack/context.claude.md
  Files selected:  <n>
  Packed tokens:   <n>
  Estimated saving: <n>%

Use it:
  claude < .agentpack/context.claude.md

Or pipe inline:
  agentpack pack --agent claude --task "..." --print | claude
```

## Subcommand routing

| User types | Action |
|---|---|
| `/agentpack` | init if needed + pack |
| `/agentpack init` | `agentpack init` only |
| `/agentpack pack ...` | `agentpack pack ...` |
| `/agentpack status` | `agentpack status` |
| `/agentpack stats` | `agentpack stats` |
| `/agentpack diff` | `agentpack diff` |
| `/agentpack summarize` | `agentpack summarize` |
| `/agentpack install` | `agentpack install --agent claude` |

## Notes

- Never overwrites existing `.agentignore` or `config.toml` without `--force`
- All commands are fully local — no LLM API calls, no network requests
- After stale detection, re-run pack automatically before reporting
