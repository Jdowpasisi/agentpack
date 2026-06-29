# GitHub Community Setup

This file tracks the GitHub-side setup that makes AgentPack easier to find and
easier to contribute to.

## Topics

Target repository topics:

- `good-first-issue`
- `help-wanted`
- `developer-tools`
- `cli`
- `python`
- `ai-coding-agent`
- `context-engine`
- `mcp`

## Labels

The canonical contributor labels live in [`.github/contributor-labels.json`](../.github/contributor-labels.json).
They include:

- `good first issue`
- `help wanted`
- `docs`
- `documentation`
- `benchmark`
- `cli`
- `python`
- `testing`

## Starter Issues

The starter issue queue lives in [`.github/contributor-issues.json`](../.github/contributor-issues.json).
It contains 15 issues, including first-time contributor tasks and four high
impact pin candidates.

## External Discovery

Good First Issue has an "Add your project" path and curates beginner-friendly
issues by language. AgentPack should be ready for submission once the starter
issues exist on GitHub with `good first issue` labels.

First Contributions is a contributor education project. For discovery there,
use the same readiness bar before proposing AgentPack in any project list:

- public repository
- active `good first issue` and `help wanted` issues
- clear `CONTRIBUTING.md`
- beginner-friendly issue acceptance criteria
- repository topics for `good-first-issue`, `help-wanted`, `developer-tools`,
  `cli`, and `python`

## Discussions

Enable GitHub Discussions in repository settings, then create these categories:

- `Roadmap`
- `Ideas`
- `Help wanted`

Discussion form templates live in [`.github/DISCUSSION_TEMPLATE/`](../.github/DISCUSSION_TEMPLATE/).

## Apply With GitHub CLI

Requires a GitHub token with write access to this repository.

```bash
python tools/github_contributor_setup.py --dry-run
python tools/github_contributor_setup.py --apply
```

The script creates missing labels, adds target topics, creates missing starter
issues, and attempts to pin the issues marked `pinned: true`.
