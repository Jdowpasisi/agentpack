# Agent Behavior Before And After AgentPack

## Before

Task: fix auth token expiry.

The agent starts cold. It searches for `auth`, opens router files, follows imports,
checks config, opens tests, and repeats that exploration after each interruption.
The useful files are eventually found, but the first several turns are spent
building a map that is not measured or reusable.

Typical cost:

| Step | Behavior |
|---|---|
| Search | Broad `rg` queries over auth/session/token names |
| Read | Several unrelated routes, middleware files, and config files |
| Verify | Test files found late or missed |
| Repeat | Same orientation work returns in later sessions |

## After

With MCP:

```text
start_task("fix auth token expiry")
```

AgentPack writes `.agentpack/task.md`, ranks the repo, and returns a compact map:

| Rank | File | Why |
|---:|---|---|
| 1 | `src/auth/token.py` | filename/content match, implementation role |
| 2 | `src/auth/session.py` | direct dependency, second-pass recall neighbour |
| 3 | `tests/test_auth.py` | paired test |

The agent still verifies the source before editing. The difference is that it
starts from a measured set of likely files, then uses `explain_file`,
`get_related_files`, and `benchmark --misses` when the map looks incomplete.

## Benchmark Proof

Use real historical tasks:

```bash
agentpack benchmark --init
agentpack benchmark --compare --misses --public-table
agentpack benchmark --public-repos --prove-targets --misses --public-table
```

Publish `benchmarks/results/YYYY-MM-DD-public.md` when the task set is real and
the expected files are the files actually changed.
