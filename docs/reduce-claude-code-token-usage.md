# Reduce Claude Code Token Usage

AgentPack can reduce context waste in Claude Code workflows by preparing a compact, task-specific context pack instead of dumping broad repo text into the prompt.

## What it reduces

- repeated file-search context
- unrelated files in prompts
- stale markdown packs
- manual repo maps rebuilt across sessions

## What it does not claim

AgentPack does not guarantee a fixed percent token reduction for every repo or task. Token savings depend on repo size, task specificity, ignore rules, and the selected context budget.

The current published v0.3.20 public release table reports:

| Metric | Result |
|---|---:|
| Avg recall | 79.2% |
| Avg token precision | 51.2% |
| Pack p50 | 1,450 tokens |
| Pack p95 | 3,805 tokens |

See [`../benchmarks/results/2026-06-11-public.md`](../benchmarks/results/2026-06-11-public.md) for the full table.

## Safer first command

Use the read-only router first:

```bash
pipx run --spec agentpack-cli agentpack route --task "fix auth token expiry"
```

Then use a full pack when you want a markdown context artifact:

```bash
agentpack work "fix auth token expiry"
```
