# v0.3.20 Baseline Comparison Plan

Baseline comparison goal:

> Show whether AgentPack finds expected files with better recall/token efficiency than simple local alternatives on the same historical commits.

## Baselines

| Baseline | What it tests |
|---|---|
| ripgrep task terms | Basic keyword search over task words |
| recent git changes | Git-only heuristic |
| import neighbors | Static dependency neighborhood |
| full repo dump | Token-heavy whole-repo context |
| no-AgentPack agent | Downstream task completion without packed context |

## Required Reporting

| Field | Required |
|---|---|
| same repos/tasks | yes |
| same expected files | yes |
| same token budget when applicable | yes |
| recall | yes |
| token precision | yes |
| p95 tokens | yes |
| misses | yes |
| downstream task success | only for guarded E2E |

Keep this separate from the 8-case smoke table until the full baseline run is published.
