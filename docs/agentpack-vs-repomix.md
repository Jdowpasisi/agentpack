# AgentPack vs Repomix

AgentPack and Repomix solve related but different context problems.

Repomix is useful when you want to bundle repository content for an AI tool. AgentPack is built for task-specific context selection before an AI coding agent edits code.

## Main difference

| Need | Better fit |
|---|---|
| Bundle a repo or folder into one promptable artifact | Repomix |
| Route one coding task to likely files, tests, rules, and skills | AgentPack |
| Preserve broad repo context for review or sharing | Repomix |
| Measure expected-file recall for coding tasks | AgentPack |
| Use MCP task routing in an agent workflow | AgentPack |

## AgentPack focus

AgentPack ranks files from task terms, symbols, imports, related tests, configs, git changes, repo history, and offline summaries. It then builds compact packs or read-only route results for agent workflows.

```bash
agentpack route --task "fix auth token expiry"
agentpack pack
```

Use Repomix when your goal is repository bundling. Use AgentPack when your goal is helping a coding agent start with the right task-specific context.
