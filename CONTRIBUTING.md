# Contributing

Thanks for helping improve AgentPack. Keep changes small, evidence-backed, and
easy to review.

## Development Setup

```bash
python -m pip install -e ".[dev]"
agentpack doctor
```

For npm wrapper changes:

```bash
npm install --prefix npm
```

## Before Opening a PR

Run the narrowest relevant tests first, then broaden when the change touches
shared behavior.

Common checks:

```bash
python -m pytest tests/test_docs_links.py -q
python -m ruff check src tests
python -m mypy
python -m pytest -q -m "not slow"
```

For release-facing changes:

```bash
python -m agentpack.cli release-check --profile docs --json
```

## Contribution Guidelines

- Prefer focused changes over broad rewrites.
- Keep generated `.agentpack/` artifacts out of commits unless a test fixture
  explicitly needs them.
- Add tests for behavior changes and regressions.
- Keep public benchmark claims tied to dated result files.
- Do not claim native hard enforcement unless the host provides a mandatory
  pre-edit or pre-tool blocking API.
- Use `agentpack route --task "<task>" --json` when another tool needs
  machine-readable routing output.

## Pull Requests

Include:

- Problem
- Solution
- Key files changed
- Validation performed
- Risk and rollback notes

If validation is not run, say so directly.
