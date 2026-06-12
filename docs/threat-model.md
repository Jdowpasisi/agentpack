# Threat Model

AgentPack reads source code to produce task-focused context. Main risk is accidental disclosure through generated context, local agent access, or logs.

## Assets

- private source code
- file paths and repo structure
- secrets accidentally committed to source
- generated context packs
- benchmark reports and result logs
- local agent configuration files

## Trust Boundaries

| Boundary | Risk | Mitigation |
|---|---|---|
| Repo source -> `.agentpack/context.md` | Sensitive code included in generated pack | `.agentignore`, redaction, receipts, manual review |
| `.agentpack/` -> local agent | Agent can read packed source excerpts | configure MCP/agent access only for trusted local clients |
| Local benchmark -> public report | Private paths or code shared accidentally | use `--anonymous-report` for aggregate-only sharing |
| Installer -> agent config | Existing rules overwritten or loosened | installers merge idempotently where possible; review diffs |
| Release artifact -> user machine | Package tampering | GitHub Actions release workflow, PyPI Trusted Publishing, npm provenance |

## Non-Goals

AgentPack does not:

- sandbox coding agents
- enforce file locks across agents
- guarantee every secret pattern is redacted
- prevent users from copying generated context into external services
- replace code review or CI security scans

## Recommended Safe Workflow

1. Add generated, vendored, export, and sensitive paths to `.agentignore`.
2. Run `agentpack route --task "..."` first for read-only orientation.
3. Run `agentpack pack --task auto` when a context artifact is needed.
4. Review context receipts and `.agentpack/context.md` before sharing.
5. Use `agentpack benchmark capture --anonymous-report` for community results.
6. Keep `.agentpack/context*.md`, cache, snapshots, and benchmark logs out of public commits unless intentionally reviewed.
