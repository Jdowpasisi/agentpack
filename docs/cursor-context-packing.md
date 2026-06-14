---
title: Cursor Context Packing
description: Use AgentPack to prepare task-focused context packs for Cursor with local repo analysis, ranked files, likely tests, and compact markdown artifacts.
---

# Cursor Context Packing

AgentPack prepares task-focused context packs for Cursor. It is useful when a repo is too large to paste and the agent needs a narrower map of files, tests, rules, and config before editing.

AgentPack runs local/offline repo analysis and builds compact context packs for AI coding agents, including Cursor.

## Cursor setup

```bash
agentpack init --agent cursor
```

This writes Cursor rules plus a VS Code task for refreshing AgentPack context. Re-running the command is idempotent.

## Task-focused context

```bash
agentpack route --task "fix auth token expiry"
agentpack task set "fix auth token expiry"
agentpack pack --task auto
```

AgentPack ranks files from task terms, symbols, imports, related tests, configs, git changes, repo history, and offline summaries. It then emits compact views such as `full`, `diff`, `symbols`, `skeleton`, or `summary` depending on relevance and token budget.

## Read-only demo

```bash
npx @vishal2612200/agentpack route --task "fix auth token expiry"
```

The route command is the safest first demo because it returns context guidance without writing a context pack.

## What Cursor receives

Cursor can use AgentPack-generated files and rules to start with:

- likely implementation files
- likely tests
- relevant configs
- repo instructions
- suggested commands
- task freshness metadata
- warnings about stale context

This is especially useful for multi-folder projects where feature code, route handlers, tests, and config live in different areas.

## What Cursor still owns

AgentPack selects a ranked starting map. Cursor and the reviewer still own code correctness, test selection, and final inspection.

AgentPack is not a coding agent. It is a context preparation layer that helps Cursor begin with a smaller, more relevant slice of the repository.
