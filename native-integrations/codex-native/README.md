# AgentPack Codex Native Stub

Status: `blocked_stub`

Codex currently uses:

- Repository rules in `AGENTS.md`.
- Codex lifecycle hooks when available.
- Version-aware generated refresh/readiness commands.
- Git auto-repack hooks.

Current enforcement level: `advisory`.

This stub tracks what would be needed for true native hard enforcement:

- A mandatory host plugin API that runs before edits or edit-capable tool calls.
- A host-level block/deny result when AgentPack readiness fails.
- Access to workspace root and the current task or prompt before edits happen.

Until those host capabilities exist, AgentPack cannot honestly mark Codex enforcement as `enforced`.
