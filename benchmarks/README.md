# AgentPack Benchmark Evidence

AgentPack treats context quality as an eval problem, not a compression claim.

Run the public source-checkout smoke suite:

```bash
agentpack benchmark --sample-fixtures --compare --misses
```

The suite uses small fixture repos committed under `tests/fixtures/`:

| Fixture | Language / shape | Example signal |
|---|---|---|
| `py_fastapi_app` | FastAPI backend | auth, routers, related tests |
| `nextjs_app` | Next.js frontend | page, auth helper, API client |
| `mixed_repo` | Python + TypeScript | cross-language utility/API tasks |
| `django_rest_app` | Django REST-style backend | pagination, serializer validation |
| `go_service` | Go service + Kubernetes | health/readiness probes, Docker deploy |
| `rails_app` | Rails-style app | mailer, background job, mailer spec |

This is a repeatable smoke suite for ranking regressions. It is intentionally
not marketed as a public leaderboard because the repos are synthetic and small.

Run the committed public real-repo smoke suite:

```bash
agentpack benchmark --public-repos --prove-targets --misses --public-table
```

That suite is defined in `benchmarks/public-repos.toml`. It uses real Pallets
Click, ItsDangerous, and MarkupSafe commits: AgentPack checks out each commit's
parent, uses the commit subject as the task, and scores against files actually
changed by that commit. The current proof artifact is
`benchmarks/results/2026-05-15-public.md`.

For additional repo-specific proof, create `.agentpack/benchmark.toml` with real
historical tasks and files that were actually changed:

```bash
agentpack benchmark --init
agentpack benchmark --compare --misses --public-table
```

Quality gates for a serious local eval:

| Metric | Target |
|---|---|
| Recall | 60%+ across task types |
| Token precision | 50%+ |
| Pack size | under 25k tokens for `balanced` |
| Miss diagnostics | every miss has status, rank, score, and reasons |
| Mode comparison | `minimal`, `balanced`, and `deep` all reported |

Before publishing benchmark claims, add a results file with this shape:

```text
benchmarks/results/YYYY-MM-DD.md
repo/task set: <repo names or anonymized domains>
agentpack version/commit: <version or sha>
cases: <count>
avg recall: <percent>
avg precision: <percent>
avg token precision: <percent>
balanced pack p50/p95 tokens: <tokens>
miss-debug command used: agentpack benchmark --compare --misses
```

Or let AgentPack write the table:

```bash
agentpack benchmark --compare --misses --public-table
```

This creates `benchmarks/results/YYYY-MM-DD-public.md` with per-repo/task rows:
task type, mode, budget, packed tokens, recall, token precision, rank@K,
runtime, and miss count. Use that table for public README or release claims.

Do not publish author-session anecdotes as benchmark proof. Use the committed
public-repo smoke suite or a documented historical-task set with expected files.

When recall is low, inspect misses before changing weights:

```bash
agentpack benchmark --misses
agentpack explain --task "your task" --file path/to/missed_file.py
agentpack explain --task "your task" --omitted
agentpack explain --task "your task" --budget-plan
```

## Deterministic Failure Evals

Use `agentpack eval` for the next reliability layer after file-selection
benchmarks. The flow is:

```bash
agentpack eval --init
# run an agent outside AgentPack, observe a real failure, then capture it
agentpack eval --capture auth-timeout --failure-class context --check "pytest tests/test_auth.py -q"
agentpack eval --case auth-timeout --prove-targets
agentpack eval --watch --until-pass
agentpack eval --replay --prove-targets
agentpack eval --variant baseline
agentpack eval --variant agentpack
agentpack eval --compare-variants baseline:agentpack
agentpack eval --ci-template
agentpack eval --report
```

`eval` is verify-only: it does not launch agents and does not ask an LLM whether
work succeeded. Cases use deterministic checks such as tests, typecheck, lint,
schema validation, API contract tests, diff size checks, forbidden file checks,
golden output comparisons, and snapshot tests. Each case carries a failure
taxonomy label (`context`, `tool`, `planning`, `reasoning`, `implementation`,
`verification`, `permission`, `format`, `hallucination`, `over_action`,
`under_action`, `harness`, `flaky`, or `spec_ambiguous`) so repeated failures
point to concrete harness, context, or workflow fixes.

Use variants to automate attribution instead of guessing. Run the same eval
case as `--variant baseline` for the no-AgentPack or old-context attempt, then
as `--variant agentpack` after packing fresh context. `agentpack eval
--compare-variants baseline:agentpack` turns result history into improved,
regressed, unchanged, and incomplete counts. During active work, `--watch
--until-pass` reruns on case, patch, golden-file, or git diff changes so
developers do not need to remember manual eval commands.

For real replay datasets, prefer `--capture` followed by `--replay`.
`--capture` writes `.agentpack/evals/<case-id>.patch` and stores context
metadata such as selected files, context hash, AgentPack version, and optional
prompt file. `--replay` creates an isolated git worktree at `base_ref`, applies
that patch, then runs checks so the case is not tied to the current dirty
worktree. Add `retries = 1` or higher to a check only when measuring flake; a
pass after an earlier failed attempt is recorded as flaky in
`.agentpack/eval_results.jsonl`.

Eval TOML is executable configuration because `checks.command` is run as a local
process. Treat shared eval files like scripts or CI workflows: review changes
before running them. For CI, `agentpack eval --ci-template` scaffolds a GitHub
Actions workflow that runs `agentpack eval --cases benchmarks/evals.toml
--replay --prove-targets`.

Captured patches are redacted before they are written. If AgentPack detects a
secret in the patch, it stores `[REDACTED:<type>]` and records
`patch_redaction_warnings` on the case. That prevents raw secret leakage, but a
case that truly depends on the secret value should be rewritten to use safe
fixture credentials before publishing or replaying broadly.
