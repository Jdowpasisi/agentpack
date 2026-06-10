# MCP Context Engine

AgentPack exposes local repo context through CLI and MCP workflows. The MCP path lets an agent request task-specific context instead of relying on one large static prompt.

## Core MCP flow

1. `start_task(task)` writes the task and creates a ranked context pack.
2. `get_context()` returns the latest pack and refreshes once when the task or repo snapshot changed.
3. `route_task(task)` returns a read-only route: relevant files, rules, skills, commands, safety warnings, and an agent prompt.
4. `get_skill(name_or_path)` loads one recommended skill's `SKILL.md` content on demand.

## Local-first design

AgentPack does not need cloud indexing, hosted LLM calls, embeddings, or a vector database for scan, summarize, rank, pack, stats, or benchmark. It uses repo-local signals such as paths, symbols, imports, tests, git changes, summaries, and configured rules.

## Try the router

```bash
agentpack route --task "fix billing webhook retry handling"
```

Use `--format json` when wiring the result into scripts:

```bash
agentpack route --task "fix billing webhook retry handling" --format json
```

Debug skill routing directly:

```bash
agentpack skills recommend --task "fix billing webhook retry handling" --explain
```

## When MCP helps

MCP is useful when agents otherwise spend turns grepping, opening files, and refreshing stale context manually. AgentPack keeps that selection step explicit, local, and measurable.
