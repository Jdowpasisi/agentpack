<!-- agentpack:start -->
## AgentPack Context

If `.agentpack/session.json` exists and `"active": true`:

1. Read `.agentpack/context.md` before making code changes.
2. For a new coding task, write a one-line summary to `.agentpack/task.md`.
3. Re-read `.agentpack/context.md` after watch mode refreshes it.
4. Use AgentPack-selected files as starting points, not as absolute truth.
5. If context is missing or stale: `agentpack session refresh`
<!-- agentpack:end -->
