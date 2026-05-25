# AgentPack Windsurf Extension Skeleton

Status: `skeleton`

This is a VS Code-style extension skeleton for Windsurf-shaped hosts. It contributes an `AgentPack: Run Guard` command that runs:

```bash
agentpack guard --agent windsurf --repair-stale --refresh-context
```

Current enforcement level: `guarded`.

Blocked from true hard enforcement until the host exposes:

- A mandatory pre-edit or pre-tool-call extension point.
- A way to block the edit/tool call when the guard command fails.
- Access to the current task or prompt before the edit happens.

Until then, this skeleton is a tracked starting point, not a production extension.
