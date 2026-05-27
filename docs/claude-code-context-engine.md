# Claude Code Context Engine

AgentPack is a local context engine for Claude Code workflows. It gives Claude a ranked starting map before edits: relevant files, likely tests, repo rules, skills, and safety warnings for the current task.

Use it when Claude Code spends early turns searching the repo, opening nearby files, and rebuilding context that could have been prepared locally first.

## Read-only route

```bash
pipx run --spec agentpack-cli agentpack route --task "fix auth token expiry"
```

`agentpack route` does not write `.agentpack/context.md`. It returns a lightweight task route for debugging, demos, or MCP-style routing.

## Claude Code setup

```bash
agentpack init --agent claude
```

This writes Claude Code instructions and MCP configuration for the repo. MCP-capable sessions should prefer AgentPack MCP tools, especially `route_task(task)` and `get_context()`, over static markdown when available.

## Why use AgentPack with Claude Code?

- Reduce repeated repo orientation work.
- Surface likely tests before edits.
- Keep selection local and explainable.
- Use benchmark cases to measure whether expected files are selected.

AgentPack is not a coding agent and does not replace Claude's source inspection. It prepares better context so Claude starts closer to the right part of the repo.
