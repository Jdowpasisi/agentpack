# AgentPack Codex Native Stub

Status: `blocked_stub`

Codex currently uses:

- Repository rules in `AGENTS.md`.
- Codex lifecycle hooks when available.
- `agentpack guard --agent codex --repair-stale --refresh-context`.
- Git auto-repack hooks.

Current enforcement level: `guarded`.

This stub tracks what would be needed for true native hard enforcement:

- A mandatory host plugin API that runs before edits or edit-capable tool calls.
- A host-level block/deny result when `agentpack guard` fails.
- Access to workspace root and the current task or prompt before edits happen.

Until those host capabilities exist, AgentPack cannot honestly mark Codex enforcement as `enforced`.
