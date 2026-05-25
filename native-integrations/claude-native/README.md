# AgentPack Claude Native Stub

Status: `blocked_stub`

Claude already has the strongest current AgentPack integration in this repo through:

- MCP tools.
- Lifecycle hooks.
- `agentpack guard --agent claude --repair-stale --refresh-context`.
- `CLAUDE.md` fallback rules.

Current enforcement level: `guarded`.

This stub tracks what would be needed for true native hard enforcement:

- A mandatory host plugin API that runs before edits or edit-capable tool calls.
- A host-level block/deny result when `agentpack guard` fails.
- Access to workspace root and the current task or prompt before edits happen.

Until those host capabilities exist, AgentPack cannot honestly mark Claude enforcement as `enforced`.
