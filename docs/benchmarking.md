# Benchmarking

Benchmarking focuses on expected-file recall for real tasks. Public release evidence lives in [`benchmarks/README.md`](../benchmarks/README.md).

## Quality Bar

AgentPack is best treated as a **ranked starting map**. It can reduce repeated orientation work, but the agent and reviewer still own correctness.

| Signal | What good looks like |
|---|---|
| Token reduction | Measure against raw repo text for your repo; savings depend on task, ignores, and budget |
| Pack size | Usually 8k-25k tokens for a specific task |
| Pack time | Seconds on a warm cache; first summarize pass is slower |
| Recall | Expected files appear near the top; validate with `agentpack benchmark --misses` |
| Precision | Good enough to reduce exploration; summaries and repo maps may still include noise |
| Freshness | Task or repo-stale MCP reads auto-refresh; static packs are clearly marked by task, git, and snapshot checks |

Use real repo evals instead of trusting compression numbers:

```bash
agentpack benchmark --init
# add historical tasks and files actually changed
agentpack benchmark --compare --misses --public-table
agentpack benchmark --release-gate
agentpack benchmark --results-template
agentpack benchmark capture --since HEAD~1 --task "describe the completed task"
```

## Skill Routing And Keyword Quality

Skill routing has its own benchmark fields. Use them when changing skill
discovery, trigger generation, BM25/domain scoring, or future semantic search
fusion.

```toml
[[cases]]
task = "review this pull request for SQL injection, XSS, and code quality"
expected_skills = ["code-reviewer"]
avoid_skills = ["generic-writing"]

[[cases]]
task = "translate my retail operations experience into a software resume"
expected_skills = ["Career Changer Translator"]
avoid_skills = ["generic-writing"]
```

Run:

```bash
agentpack benchmark --misses
```

The summary table and `.agentpack/benchmark_results.jsonl` report:

| Metric | Meaning |
|---|---|
| `skill_recall_at_3` | fraction of expected skills found in the top three |
| `skill_precision_at_3` | fraction of top-three skills that are expected |
| `skill_mrr` | reciprocal rank of the first expected skill |
| `skill_noise_rate` | fraction of top-three skills matching `avoid_skills` |
| `selected_skills` | actual top skill recommendations |

For keyword quality, write cases around the user wording that previously failed.
The goal is not to preserve a static trigger list; it is to prove that real task
phrases select the right skill and avoid broad generic recommendations.

`agentpack benchmark --release-gate` is the public release gate. It expands to
`--public-repos --prove-targets --misses --public-table`, reads
`benchmarks/public-repos.toml` by default, and can use `--public-repos-cache`
or `--refresh-public-repos`.

For external claims, use several real repositories or anonymized historical task
sets and publish the generated table from `benchmarks/results/*-public.md`.
This repo includes a curated public smoke suite in
`benchmarks/public-repos.toml`; it evaluates real commits from Pallets Click,
ItsDangerous, and MarkupSafe by checking out each commit's parent and scoring
against files actually changed by the commit. Synthetic fixtures are useful
regression tests, but should not be presented as market proof.

`agentpack benchmark --sample-fixtures` is intentionally labeled as regression
smoke. It proves the benchmark harness still catches known scenarios in this
source checkout; it is not release evidence for ranking quality across public
repositories.

Use `agentpack benchmark capture --since <ref> --task "..."` after a real task
to append a reusable case to `.agentpack/benchmark.toml`. It infers
`expected_files` from `git diff --name-only <ref> HEAD`. Use
`agentpack benchmark --from-history N --write-cases` only as scaffolding;
history-derived cases need manually filled `expected_files` before they prove
recall.

## Download Stats

npm exposes official package download counts through its public registry API and the npm downloads badge above:

```bash
curl https://api.npmjs.org/downloads/point/last-month/%40vishal2612200%2Fagentpack
curl https://api.npmjs.org/downloads/point/last-week/%40vishal2612200%2Fagentpack
```

PyPI does not show official project download counts on package pages. For rough trend data on the Python core package, use third-party mirrors:

```bash
curl https://pypistats.org/api/packages/agentpack-cli/recent
```

- PyPI Stats: <https://pypistats.org/packages/agentpack-cli>
- pepy.tech: <https://pepy.tech/project/agentpack-cli>
