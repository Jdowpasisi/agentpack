<!-- agentpack:block:start -->
skills:
  - agentpack

At the start of every coding task:
1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `agentpack guard --agent antigravity --repair-stale --refresh-context`.
3. Prefer AgentPack MCP if available. MCP is the active path. Call `agentpack_readiness()` to prove live tool exposure, then `agentpack_route_task(task="<task>")` to get files, rules, skills, commands, and safety warnings.
4. Call `agentpack_pack_context(task="<task>")` only when full packed context is needed, or `agentpack_get_context()` for current context.
5. If MCP is unavailable, read `.agent/skills/agentpack/SKILL.md`. Treat it as fallback; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, rerun the guard command before using selected files.
6. Use files listed in context as starting points, but verify with actual code before editing.

When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the refresh command before editing.

If AgentPack tools are unavailable or context looks stale/wrong-worktree, do not trust old pack output. Use direct `rg`, PR diff inspection, and target-file reads, then run focused validation.
For multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. Use `AGENTPACK_THREAD_ID=<stable-id> agentpack guard --agent antigravity --repair-stale --refresh-context --thread auto` or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings.
<!-- agentpack:block:end -->
