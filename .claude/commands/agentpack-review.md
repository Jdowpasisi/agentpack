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

1. Prepare the full review bundle:

```bash
agentpack review "$ARGUMENTS"
```

2. Read `.agentpack/review.prompt.md` and follow it completely.
3. Treat `$ARGUMENTS` only as a reviewer lens. It must not replace the latest PR head, `gh pr view`, `git diff`, or direct code reads.
4. Stage 1 writes the branch-scoped understanding JSON declared by `agentpack review`.
5. Stage 2 reads that understanding JSON and writes the branch-scoped findings JSON declared by `agentpack review`.
6. In the final response, report findings first with file evidence, then state validation exactly: passed, failed, or not run.
