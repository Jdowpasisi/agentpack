---
title: AgentPack vs Repomix
description: Compare AgentPack and Repomix for AI coding agent context, repo bundling, task-specific file ranking, MCP workflows, and benchmarkable context packs.
---

# AgentPack vs Repomix

AgentPack and Repomix solve related but different context problems.

Repomix is useful when you want to bundle repository content for an AI tool. AgentPack is built for task-specific context selection before an AI coding agent edits code.

## Main difference

| Need | Better fit |
|---|---|
| Bundle an exact repo or folder dump into one promptable artifact | Repomix |
| Route one coding task to likely files, tests, rules, and skills | AgentPack |
| Preserve curated broad repo context for review or sharing with receipts | AgentPack |
| Build compact task-focused context packs | AgentPack |
| Measure expected-file recall for coding tasks | AgentPack |
| Use MCP task routing in an agent workflow | AgentPack |
| Avoid hosted indexing, embeddings, or vector databases for core flow | AgentPack |

## AgentPack focus

AgentPack ranks files from task terms, symbols, imports, related tests, configs, git changes, repo history, and offline summaries. It then builds compact packs or read-only route results for agent workflows.

```bash
agentpack route --task "fix auth token expiry"
agentpack pack
```

AgentPack is best when the question is:

> For this concrete coding task, which files, tests, rules, and commands should the agent inspect first?

## Repomix focus

Repomix is best when the question is:

> How do I package this repository or folder into one artifact that an AI tool can read?

That broad bundle can be useful for audits, explanations, reviews, or sharing repo context outside the original project.

AgentPack now covers the adjacent workflow inside `pack` and `review`: it can add curated broad repo context, module summaries, inventory receipts, freshness metadata, and redaction warnings to the normal context artifact when the task asks for review, sharing, audit, or repo overview. It is still not trying to be an exact whole-repo dumper.

## Workflow comparison

AgentPack is task-first:

```bash
agentpack route --task "fix billing webhook retry handling"
```

Repomix is bundle-first:

```bash
repomix
```

These workflows can coexist. Use Repomix for exact broad repository packaging. Use AgentPack when an AI coding agent needs a ranked, compact, task-specific starting map or a curated broad review/share artifact in the existing workflow.

## Measurement

AgentPack includes benchmark commands for expected-file recall and token precision:

```bash
agentpack benchmark --release-gate
agentpack benchmark --misses
```

That matters when teams want to know whether context packs select the files that actually changed for real tasks.

## Bottom line

Use Repomix when your goal is an exact repository dump. Use AgentPack when your goal is helping a coding agent start with the right task-specific context, including curated broad context for review or sharing.
