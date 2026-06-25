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
3. By default, `agentpack review` starts a fresh run under `.agentpack/reviews/<branch>/<run_id>/` and refreshes the stable alias files in `.agentpack/`.
4. Stage 1 writes the run-scoped understanding TOON at the output path declared by `agentpack review`.
5. Stage 2 reads that understanding TOON and writes the run-scoped findings TOON at the output path declared by `agentpack review`.
6. Resume an interrupted run only with `agentpack review --resume <run_id>`.
7. Use the latest PR head, `gh pr view`, `git diff`, and direct code reads as source of truth.
8. Treat `$ARGUMENTS` only as a prioritization lens. It must not replace code evidence.
9. Report findings first with file evidence, then state validation exactly: passed, failed, or not run.
