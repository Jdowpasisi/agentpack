# v0.3.20 Public Benchmark Methodology

Reproduce the public suite:

```bash
agentpack benchmark --public-suite --reproduce v0.3.20
```

The suite is defined in [`../../public-repos.toml`](../../public-repos.toml).

## Case Selection

- 8 pinned Pallets smoke commits remain fixed regression anchors.
- 100+ sampled historical commits come from Python, TypeScript, Go, Java, and monorepo repositories.
- Sampled commits use first-parent, non-merge git history.
- Each case checks out the parent of the target commit.
- The commit subject becomes the benchmark task.
- `expected_files` are files actually changed by the target commit.
- Large or noisy commits are filtered with `include_globs`, `exclude_globs`, and `max_changed_files`.

## Metrics

| Metric | Meaning |
|---|---|
| Recall | Fraction of expected files selected in the pack |
| Token precision | Fraction of packed tokens spent on expected files |
| Rank@K | Rank where all expected files appear in the scored list |
| p50/p95 tokens | Packed-token distribution |
| Misses | Expected files not selected under the configured budget |

## Baselines

Baseline comparisons should be reported separately from AgentPack results:

- ripgrep task-term search
- recent git changes
- import-neighbor selection
- full repo dump / Repomix-style packing
- downstream agent with no AgentPack

Do not claim downstream success improvement unless guarded E2E runs compare the same task, repo, agent, and validation command.
