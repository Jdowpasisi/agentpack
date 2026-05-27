# AI Coding Agent Context Packing

AgentPack is a local context packing tool for AI coding agents such as Claude Code, Codex, Cursor, Windsurf, and Antigravity. It prepares the task-specific repo context an agent should inspect before editing.

## Problem

Large repos create context waste:

- broad file searches before every task
- missed tests or config files
- repeated orientation across sessions
- stale context after active edits
- hard-to-measure file selection quality

## AgentPack approach

AgentPack ranks files for one concrete task, then builds a compact context pack with protected space for changed files, tests, docs, and dependencies. It also exposes a lighter `route` surface for files, rules, skills, commands, and warnings.

```bash
agentpack route --task "fix flaky payment webhook test"
agentpack pack
```

## Measuring quality

Use benchmarks to compare selected files against files actually changed for real tasks:

```bash
agentpack benchmark --release-gate
agentpack benchmark --misses
```

The public release gate is smoke proof, not a universal guarantee. Add cases from your own repo when tuning selection quality.
