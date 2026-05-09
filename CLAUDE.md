<!-- agentpack:start -->
## AgentPack Context

At the start of every coding task:

1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Read `.agentpack/context.claude.md` — context is injected automatically via session hooks.
3. Use files listed in context as starting points, but verify with actual code before editing.

If context is missing or stale, regenerate manually:

```bash
agentpack pack --agent claude --task "<task>"
```

Then read `.agentpack/context.claude.md`.
<!-- agentpack:end -->
