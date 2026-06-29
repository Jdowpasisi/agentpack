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

## Finding A First Issue

Start with issues labeled `good first issue`. These should have a narrow scope,
clear files or docs areas, and acceptance criteria that can be verified without
knowing the whole codebase.

Useful labels:

| Label | Meaning |
|---|---|
| `good first issue` | Small, well-scoped task for a first contribution |
| `help wanted` | Maintainers want community help or feedback |
| `docs` / `documentation` | Documentation-only or documentation-heavy work |
| `benchmark` | Benchmark cases, result docs, or evidence tooling |
| `cli` | Command-line behavior, flags, help text, or output contracts |
| `python` | Python package implementation work |
| `testing` | Tests, fixtures, release checks, or validation coverage |

If you are unsure where to start, comment on a `help wanted` issue with what you
want to work on. Maintainers should confirm scope before larger changes.

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
- For benchmark changes, keep claims tied to dated result files and explain what
  the benchmark proves and does not prove.
- For CLI changes, preserve existing flags unless there is a documented
  compatibility reason to change them.
- For type-safety changes, expand `mypy` coverage module by module with focused
  tests.

## Pull Requests

Include:

- Problem
- Solution
- Key files changed
- Validation performed
- Risk and rollback notes

If validation is not run, say so directly.
