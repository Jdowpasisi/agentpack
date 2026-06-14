# Codex Plugin

AgentPack can be packaged as a thin Codex plugin so Codex starts with ranked repo context.

The plugin does not reimplement ranking, scanning, packing, MCP, or benchmarking. It delegates to the existing local AgentPack CLI and MCP behavior.

AgentPack remains a local context engine, not a coding agent.

This is the first concrete packaged plugin. The broader plugin and IDE distribution plan covers Cursor, Windsurf, Claude Code, Antigravity, and generic agents in [`agent-plugins.md`](agent-plugins.md).

## What It Adds

- `@agentpack` checks whether context exists and suggests the next step.
- `@agentpack-route <task>` runs read-only task routing.
- `@agentpack-pack <task>` writes the task and builds `.agentpack/context.md`.
- `@agentpack-refresh [task]` refreshes stale context through the Codex guard path.
- `@agentpack-review` inspects the diff and suggests benchmark capture or missing checks.

## Install

This repo can act as a local Codex plugin package because it includes:

```text
.codex-plugin/plugin.json
skills/
```

Install or load it through Codex's local plugin workflow, pointing Codex at this repository as the plugin source.

Install AgentPack locally first:

```bash
pipx install agentpack-cli
agentpack --version
```

Inside a project repo, initialize normal AgentPack files:

```bash
agentpack init --agent auto
```

When auto-detection resolves to Codex, this writes `AGENTS.md`,
`.codex/hooks.json`, git hooks, and a local Codex plugin package under
`~/.codex/plugins/cache/local/agentpack/<version>/`. Auto-detection does not
default to Codex; pass `--agent codex` only when you want to force Codex setup.

For existing repos after upgrading AgentPack:

```bash
agentpack upgrade --agent auto
```

The plugin commands stay thin and call the same local engine.

## Codex Workflow

Start read-only:

```text
@agentpack-route fix auth token expiry
```

Build context when Codex needs more than a route:

```text
@agentpack-pack fix auth token expiry
```

Then Codex should read `.agentpack/context.md`, inspect selected files, and verify with normal repo search before editing.

After edits:

```text
@agentpack-review
```

Review should inspect `git diff`, run or recommend checks, and optionally capture a benchmark case.

## Rules For Codex

Before making code changes:

1. Understand the task.
2. Use AgentPack route or pack when repo context is unclear.
3. Read `.agentpack/context.md` if it exists.
4. Treat selected files as starting points, not the full truth.
5. Use normal repo search when AgentPack output seems incomplete.
6. Prefer the smallest correct diff.
7. Run relevant checks after editing.

## Local-First Boundary

The plugin calls local AgentPack commands. It does not upload code, call LLM APIs, or turn AgentPack into an autonomous agent.

Generated files live under `.agentpack/`. Review packs before sharing them outside your machine.
