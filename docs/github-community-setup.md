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
issues by language. Its published criteria include at least three open issues
with `good first issue`, at least ten contributors, setup instructions,
`CONTRIBUTING.md`, recent activity, and a license.

Current live status checked before this file was updated:

- open starter issues: `15` (`#20` through `#34`)
- open issues with `good first issue`: `9`
- contributor count from GitHub contributors API: `4`
- repository permission for the current `gh` token: `READ`
- missing target topics: `good-first-issue`, `help-wanted`, `cli`, `python`
- missing specialized labels: `docs`, `benchmark`, `cli`, `testing`

AgentPack should be submitted to Good First Issue after the target topics and
specialized labels are applied and the contributor-count criterion is met.

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
Because this setup creates labels, repository topics, pins, and labeled issues,
the script requires `ADMIN` or `MAINTAIN` permission as reported by `gh repo
view --json viewerPermission`.

```bash
python tools/github_contributor_setup.py --dry-run
python tools/github_contributor_setup.py --apply
```

The script creates missing labels, adds target topics, creates missing starter
issues, reconciles labels on existing starter issues, and attempts to pin the
issues marked `pinned: true`.
