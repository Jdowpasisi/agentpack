# Cursor Context Packing

AgentPack prepares task-focused context packs for Cursor. It is useful when a repo is too large to paste and the agent needs a narrower map of files, tests, rules, and config before editing.

## Cursor setup

```bash
agentpack init --agent cursor
```

This writes Cursor rules plus a VS Code task for refreshing AgentPack context. Re-running the command is idempotent.

## Task-focused context

```bash
agentpack work "fix auth token expiry"
```

AgentPack ranks files from task terms, symbols, imports, related tests, configs, git changes, repo history, and offline summaries. It then emits compact views such as `full`, `diff`, `symbols`, `skeleton`, or `summary` depending on relevance and token budget.

## Read-only demo

```bash
npx @vishal2612200/agentpack route --task "fix auth token expiry"
```

The route command is the safest first demo because it returns context guidance without writing a context pack.

## What Cursor still owns

AgentPack selects a ranked starting map. Cursor and the reviewer still own code correctness, test selection, and final inspection.
