# AgentPack E2E A/B Cases

Use this folder for public AgentPack vs no-AgentPack outcome runs. File-selection
benchmarks prove whether the right files were selected; E2E runs prove whether a
coding agent finished better with AgentPack guidance.

Run shape:

```bash
agentpack benchmark e2e-init --output benchmarks/e2e/cases.toml
# Fill cases with real repos, setup commands, validation commands, protected tests,
# and expected edit paths.
agentpack benchmark e2e \
  --cases benchmarks/e2e/cases.toml \
  --agent-command 'bash -lc "codex exec --cd {repo} \"$(cat {prompt})\""' \
  --strategies no-context,agentpack \
  --trials 3 \
  --output benchmarks/results/e2e-results.jsonl
agentpack benchmark e2e-report \
  --results benchmarks/results/e2e-results.jsonl \
  --baseline no-context \
  --treatment agentpack \
  --markdown > benchmarks/results/YYYY-MM-DD-e2e-ab.md
```

Minimum report metrics:

- task success rate
- validation pass rate
- expected file touch rate
- tool calls
- token usage and estimated cost
- time to first correct file
- wall time
- AgentPack noise or slowdown cases

Until a dated `benchmarks/results/*-e2e-ab.md` report exists, public docs must
describe E2E proof as pending and keep benchmark claims scoped to file
selection.
