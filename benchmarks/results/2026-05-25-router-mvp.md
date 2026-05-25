# AgentPack Router MVP Smoke Benchmark — 2026-05-25

Environment:
- Repo: AgentPack feature branch `codex/task-router-mvp`
- Python: local `.venv` on Python 3.12
- Task: `fix flaky payment webhook test`
- Inventory: 204 skills, 2 rules

Commands:

```bash
/usr/bin/time -p .venv/bin/agentpack skills scan > /tmp/agentpack-skills-scan.txt
/usr/bin/time -p .venv/bin/agentpack skills index > /tmp/agentpack-skills-index.txt
/usr/bin/time -p .venv/bin/agentpack route --task "fix flaky payment webhook test" --format json > /tmp/agentpack-route-current.json
/usr/bin/time -p .venv/bin/agentpack route --task "fix flaky payment webhook test" --format json > /tmp/agentpack-route-indexed.json
```

Results:

| Operation | Real time | Notes |
|---|---:|---|
| `skills scan` | 1.86s | live discovery of local + global skills |
| `skills index` | 0.64s | wrote metadata-only `.agentpack/skills_index.json` |
| `route` without pre-existing index | 4.69s | includes PackPlanner ranking + live inventory |
| `route` with index | 2.62s | includes PackPlanner ranking + indexed inventory |

Indexed route output:
- selected files: 20
- selected skills: 3
- applied rules: 2
- suggested commands: 2
- safety warnings: 125

MCP stdio smoke:
- server listed `route_task`, `get_skills`, and `explain_route`
- `route_task("fix flaky payment webhook test")` returned valid JSON with 20 files, 3 skills, 2 rules, and 2 command suggestions

Interpretation:
- Router runtime is currently dominated by `PackPlanner` ranking, not skill discovery.
- Metadata indexing cuts this repo's route runtime by roughly 44%.
- External side-effect warnings are intentionally noisy with large global skill inventories; this is safer than silently selecting external skills.
