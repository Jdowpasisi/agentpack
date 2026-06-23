---
name: agentpack-review
description: Run the full AgentPack PR review flow for the current branch or PR with an optional reviewer lens.
---

# AgentPack Review

Use when the user invokes `@agentpack-review` or `@agentpack-review <reviewer context>`.

Do not claim correctness unless relevant checks actually ran.

## Steps

1. Prepare the full review bundle:

```bash
agentpack review "$ARGUMENTS"
```

2. Read `.agentpack/review.prompt.md` and follow it end to end.
3. Stage 1 writes the branch-scoped understanding JSON at the output path declared by `agentpack review`.
4. Stage 2 reads that understanding JSON and writes the branch-scoped findings JSON at the output path declared by `agentpack review`.
5. Use the latest PR head, `gh pr view`, `git diff`, and direct code reads as source of truth.
6. Treat `$ARGUMENTS` only as a prioritization lens. It must not replace code evidence.
7. Report findings first with file evidence, then state validation exactly: passed, failed, or not run.
