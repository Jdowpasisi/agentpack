<!-- agentpack:start -->
## AgentPack

AgentPack MCP server is available. For coding tasks in this repository, call the MCP tool
before editing files to get task-relevant context without loading the entire codebase.

```
mcp__agentpack__pack_context(task="<what you're working on>", budget=4000)
```

Other tools:
- `mcp__agentpack__explain_file(path)` — score breakdown + symbols for a file
- `mcp__agentpack__get_related_files(path)` — import-graph neighbours
- `mcp__agentpack__get_stats()` — token/saving stats for the latest pack
- `mcp__agentpack__get_context()` — read the pre-built pack (no repack)
- `mcp__agentpack__refresh()` — refresh using current task.md

If MCP is not available, fall back to the CLI:

```bash
agentpack pack --agent claude --task "<task>"
```

Then read `.agentpack/context.claude.md`.
<!-- agentpack:end -->
