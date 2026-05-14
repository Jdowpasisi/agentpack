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
For credible repo-specific proof, create `.agentpack/benchmark.toml` with real
historical tasks and files that were actually changed:

```bash
agentpack benchmark --init
agentpack benchmark --compare --misses
```

Quality gates for a serious local eval:

| Metric | Target |
|---|---|
| Recall | 60%+ across task types |
| Token precision | 50%+ |
| Pack size | under 25k tokens for `balanced` |
| Miss diagnostics | every miss has status, rank, score, and reasons |
| Mode comparison | `minimal`, `balanced`, and `deep` all reported |

When recall is low, inspect misses before changing weights:

```bash
agentpack benchmark --misses
agentpack explain --task "your task" --file path/to/missed_file.py
agentpack explain --task "your task" --omitted
agentpack explain --task "your task" --budget-plan
```
