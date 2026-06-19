# AgentPack Claude Native Stub

Status: `blocked_stub`

Claude already has the strongest current AgentPack integration in this repo through:

- MCP tools.
- Lifecycle hooks.
- Version-aware generated refresh/readiness commands.
- `CLAUDE.md` fallback rules.

Current enforcement level: `advisory`.

This stub tracks what would be needed for true native hard enforcement:

- A mandatory host plugin API that runs before edits or edit-capable tool calls.
- A host-level block/deny result when AgentPack readiness fails.
- Access to workspace root and the current task or prompt before edits happen.

Until those host capabilities exist, AgentPack cannot honestly mark Claude enforcement as `enforced`.
