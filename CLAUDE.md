<!-- agentpack:start -->
## AgentPack

AgentPack MCP server is available. For coding tasks in this repository, call the MCP tool
before editing files to get task-relevant context without loading the entire codebase.
Prefer MCP over reading `.agentpack/context*.md` directly because MCP auto-refreshes stale task
and repo-snapshot context before returning.

```
mcp__agentpack__get_context()
```

For a brand-new task, call:

```
mcp__agentpack__pack_context(task="<what you're working on>", budget=4000)
```

Executable fallback guard:

```bash
agentpack guard --agent claude --repair-stale --refresh-context
```

Other tools:
- `mcp__agentpack__explain_file(path)` — score breakdown + symbols for a file
- `mcp__agentpack__get_related_files(path)` — import-graph neighbours
- `mcp__agentpack__get_stats()` — token/saving stats for the latest pack
- `mcp__agentpack__get_context()` — read the latest pack; auto-refreshes when task.md or repo snapshot changed
- `mcp__agentpack__refresh()` — refresh using current task.md

If MCP is not available, fall back to the CLI:

```bash
printf '%s\n' "<task>" > .agentpack/task.md
agentpack pack --agent claude --task auto
```

Then read `.agentpack/context.claude.md`.
<!-- agentpack:end -->
