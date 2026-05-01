<!-- agentpack:start -->
## AgentPack Context

Before working on any task:

1. Ensure the context pack exists and is fresh:
   ```bash
   agentpack pack --agent codex --task auto --mode balanced
   ```
2. Read `.agentpack/context.md` in full before starting work.

Regenerate any time the task or files change:

```bash
agentpack pack --agent codex --task "<task>"
```

Use the context pack as the primary task-specific repo context.
<!-- agentpack:end -->
