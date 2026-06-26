---
description: Run the full AgentPack PR review flow with an optional reviewer lens.
---

# AgentPack Review

Review the current PR or checked-out branch using the full AgentPack review workflow.

## Usage

```
/agentpack-review
/agentpack-review focus on backward compatibility
/agentpack-review reviewer is worried about prompt latency
```

## Steps

1. Refresh AgentPack context for this exact review task before reading PR diff or code. Prefer MCP:

```text
agentpack_pack_context(task="review current PR $ARGUMENTS")
```

If MCP is unavailable, run:

```bash
agentpack guard --agent auto --repair-stale --refresh-context
```

If you bypass this refresh, state the bypass reason before continuing.
2. Prepare the full review bundle:

```bash
agentpack review "$ARGUMENTS"
```

3. Read `.agentpack/review.prompt.md` and follow it completely.
4. Treat `$ARGUMENTS` only as a reviewer lens. It must not replace the latest PR head, `gh pr view`, `git diff`, or direct code reads.
5. By default, `agentpack review` starts a fresh run under `.agentpack/reviews/<branch>/<run_id>/` and refreshes the stable alias files in `.agentpack/`.
6. Do not perform the review inline from this command. If you cannot write the required files, stop and report blocked.
7. Stage 1 writes the run-scoped understanding TOON declared by `agentpack review`.
8. Stage 2 must read that understanding TOON from disk and then write the run-scoped findings TOON declared by `agentpack review`.
9. Do not produce a final review summary unless the findings TOON exists at the declared path and validates.
10. Resume an interrupted run only with `agentpack review --resume <run_id>`.
11. In the final response, report findings first with file evidence, then state validation exactly: passed, failed, or not run.
