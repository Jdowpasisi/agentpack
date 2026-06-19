# AgentPack Windsurf Extension Skeleton

Status: `skeleton`

This is a VS Code-style extension skeleton for Windsurf-shaped hosts. It contributes an AgentPack readiness command that defaults to:

```bash
agentpack doctor --agent windsurf
```

Current enforcement level: `advisory`.

Blocked from true hard enforcement until the host exposes:

- A mandatory pre-edit or pre-tool-call extension point.
- A way to block the edit/tool call when AgentPack readiness fails.
- Access to the current task or prompt before the edit happens.

Until then, this skeleton is a tracked starting point, not a production extension.
