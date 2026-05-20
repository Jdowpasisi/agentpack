# AgentPack Native Integration Skeletons

This directory tracks the path from best-effort repo rules to true native host enforcement.

AgentPack can already refresh context through MCP, lifecycle hooks, `agentpack guard`, pack self-healing, and `agentpack migrate`. True hard enforcement still requires the host app to expose a mandatory pre-edit or pre-tool-call API that can block edits when the guard fails.

## Enforcement Contract

A native host integration must provide all of these capabilities before AgentPack can mark it as `enforced`:

- Mandatory activation before an agent edits files or runs edit-capable tools.
- Workspace root access.
- Current prompt or task access, or an equivalent task-change signal.
- Ability to run `agentpack guard --agent <agent> --repair-stale --refresh-context` or call AgentPack MCP.
- Ability to block the edit/tool call when AgentPack returns a non-zero guard result.

If any capability is missing, the integration remains `guarded`: useful and loud, but not hard-enforced.

## Status Index

`status.json` is the machine-readable source of truth. Each entry has:

- `status`: `skeleton` or `blocked_stub`.
- `enforcement_level`: currently `guarded`; future native host APIs can upgrade this to `enforced`.
- `blocked_on`: exact host capabilities needed before hard enforcement is honest.

## Current Stubs

- `cursor-extension/`: VS Code-style extension skeleton for Cursor-shaped environments.
- `windsurf-extension/`: VS Code-style extension skeleton for Windsurf-shaped environments.
- `claude-native/`: tracked native stub, blocked on mandatory host plugin API.
- `codex-native/`: tracked native stub, blocked on mandatory host plugin API.
