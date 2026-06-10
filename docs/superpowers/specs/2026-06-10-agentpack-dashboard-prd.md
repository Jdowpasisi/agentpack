# AgentPack Dashboard PRD

## Problem Statement

AgentPack has grown into a local context and skill-routing system, but its outputs are scattered across CLI commands and files under `.agentpack/`. A developer can generate context, inspect status, route a task, collect learning notes, record skill feedback, and run benchmarks, but there is no single local surface that explains what AgentPack currently knows, why it made those choices, and whether those choices improved over time.

That visibility gap creates three product risks:

1. Users cannot quickly decide whether the current context is fresh enough to trust.
2. Users cannot easily audit selected files, skill recommendations, feedback, and learning artifacts together.
3. AgentPack cannot clearly demonstrate that context selection, skill routing, and learning loops are improving.

The dashboard should become AgentPack's local control plane: a read-only, source-backed view of project context, skill routing, learning, and quality signals, with safe paths toward feedback and global memory.

## Solution

Build a local-first `agentpack dashboard` command that generates a static HTML dashboard and an optional JSON snapshot from existing AgentPack artifacts. The MVP should be read-only and should never require a server, login, cloud upload, or external JavaScript.

The dashboard should answer:

- What task is AgentPack working on?
- Is the context fresh, stale, missing, or thread-scoped?
- Which files were selected, in what include mode, and why?
- Which skills were recommended, with what confidence and side-effect risk?
- What feedback exists for recommended, used, ignored, or noisy skills?
- What learning artifacts exist from the latest tasks?
- What benchmark and routing metrics show quality or regressions?
- What command should the user run next?

V2 can add a local-only server for direct actions. V3 can add global cross-project aggregation and lesson promotion. The MVP should establish the normalized data model and static rendering path so later interaction can reuse the same snapshot.

## User Stories

1. As a developer, I want to see the current task, so that I know what AgentPack is optimizing for.
2. As a developer, I want to see context freshness, so that I do not start an agent with stale context.
3. As a developer, I want to see the last context generation time, mode, token counts, and savings, so that I understand the cost and freshness of the pack.
4. As a developer, I want to see selected files with include mode, score, token estimate, and reasons, so that I can audit the context selection.
5. As a developer, I want to see omitted expected files from benchmark runs, so that I can understand context misses.
6. As a developer, I want to see recommended skills with confidence, score, side-effect level, baseline/task-specific category, and reasons, so that I understand the intended agent guidance.
7. As a developer, I want to see whether a skill was used, helpful, ignored, noisy, or marked as a bad recommendation, so that the trust loop is visible.
8. As a developer, I want copyable skill-feedback commands, so that the static dashboard can improve future routing without JavaScript actions.
9. As a developer, I want to see learning notes, daily summaries, future-agent lessons, and skill progress links, so that learning artifacts are discoverable.
10. As a developer, I want to see benchmark metrics such as file recall, token precision, skill recall, skill precision, MRR, and noise rate, so that I can judge routing quality.
11. As a developer, I want suggested next commands, so that empty or stale states are actionable.
12. As a developer using multiple AgentPack threads, I want the dashboard to show active thread metadata and conflict warnings, so that parallel work does not silently collide.
13. As a team lead, I want a later global view of projects, skill usage, noisy recommendations, and candidate lessons, so that team learning can be reviewed without collecting private code.
14. As a security-conscious user, I want the dashboard to be local-only, static by default, and free of remote scripts, so that repo data does not leave my machine.

## MVP Scope

The first release should ship:

- `agentpack dashboard`
- `agentpack dashboard --open`
- `agentpack dashboard --json`

MVP output:

- `.agentpack/dashboard.html`
- JSON to stdout for `--json`

MVP inputs:

- `.agentpack/pack_metadata.json`
- `.agentpack/task.md`
- `.agentpack/task_state.md`
- `.agentpack/metrics.jsonl`
- `.agentpack/benchmark_results.jsonl`
- `.agentpack/skill_feedback.jsonl`
- `.agentpack/learning-feedback.jsonl`
- `.agentpack/skills-progress.json`
- `.agentpack/learning.md`
- `.agentpack/daily-summary.md`
- `.agentpack/agent-lessons.md`
- `.agentpack/thread_index.jsonl`
- `.agentpack/threads/*/pack_metadata.json`
- `.agentpack/threads/*/task_state.md`

The MVP should degrade gracefully when any artifact is absent. Missing files should show empty states with concrete commands, not stack traces.

## Later Scope

V2 should add:

- `agentpack dashboard --global`
- `~/.agentpack/projects.json`
- `~/.agentpack/dashboard.html`
- Global skill memory aggregation from local project feedback
- Candidate global lesson inbox

V3 should add:

- `agentpack dashboard --serve`
- Local-only server bound to `127.0.0.1`
- Direct actions for skill feedback
- Direct actions for promote/reject global lessons
- Buttons to run safe local commands such as refresh, benchmark, and learn

Team mode should remain separate:

- redacted team dashboard export
- CI artifact generation
- opt-in team lesson export

## Functional Requirements

### Project Overview

The dashboard must show:

- project name
- absolute project path
- current task
- task state: `planned`, `in_progress`, `blocked`, `done`, or `unknown`
- git branch and SHA when available
- last context generation timestamp
- context status: `fresh`, `stale`, `missing`, or `unknown`
- thread id when thread-scoped context is active
- active thread count and conflicts when available

### Context Health

The dashboard must show:

- packed tokens
- raw tokens
- saving percentage
- mode: `lite`, `minimal`, `balanced`, or `deep`
- selected file count
- ignored/binary file count when available
- full scan reason or incremental scan status when available
- freshness reason if stale
- next command when context is missing or stale

### File Selection View

The dashboard must show a table of selected files:

- path
- include mode
- score
- token estimate when available
- top reasons
- role or matched domain when available

The view should include benchmark miss summaries when available:

- expected files missed
- miss status
- reason or remediation if present

### Skill Routing View

The dashboard must show:

- selected skills
- baseline skills separately from task-specific skills
- confidence score
- raw score
- side-effect level
- source path
- selection reasons
- feedback state derived from `.agentpack/skill_feedback.jsonl`

Feedback state should distinguish:

- recommended only
- used and helpful
- used and noisy
- ignored
- bad recommendation

Recommended-only skills must not be rendered as successful.

### Feedback Guidance

The static dashboard must render copyable commands for common feedback actions:

```bash
agentpack skills feedback --task "..." --recommended-skill skill-name --used-skill skill-name --tests-passed --user-feedback helpful
agentpack skills feedback --task "..." --ignored-skill skill-name --user-feedback ignored
agentpack skills feedback --task "..." --bad-recommendation skill-name --user-feedback noisy
```

The dashboard should not execute these commands in MVP.

### Learning View

The dashboard must show whether these artifacts exist and link to them:

- `.agentpack/learning.md`
- `.agentpack/daily-summary.md`
- `.agentpack/agent-lessons.md`
- `.agentpack/skills-progress.json`
- `.agentpack/learning-feedback.jsonl`

When content is small and safe, the dashboard may show a bounded excerpt. It must not inline unbounded Markdown or JSONL content.

### Benchmark View

The dashboard must show latest and recent averages when present:

- file recall
- file precision
- token precision
- rank@K
- skill recall@3
- skill precision@3
- skill MRR
- skill noise rate
- case count
- pass/fail status of release gate metrics when available

### Suggested Actions

The dashboard must show commands based on current state:

- no `.agentpack/`: `agentpack init --yes`
- no task: `agentpack work "describe the task"`
- stale context: `agentpack pack --task auto`
- no learning: `agentpack learn`
- no benchmark data: `agentpack benchmark --init`
- no skill feedback: `agentpack skills feedback ...`

## Data Model

The command should normalize project artifacts into a JSON-safe snapshot:

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-10T10:30:00Z",
  "project": {
    "name": "agentpack",
    "path": "/Users/vishal/projects/agentpack",
    "branch": "main",
    "git_sha": "abc123"
  },
  "task": {
    "text": "fix auth token expiry",
    "state": "in_progress",
    "thread_id": null
  },
  "context": {
    "status": "fresh",
    "generated_at": "2026-06-10T10:30:00Z",
    "mode": "balanced",
    "packed_tokens": 1450,
    "raw_tokens": 40000,
    "saving_pct": 96.3,
    "selected_files_count": 8,
    "stale_reason": ""
  },
  "selected_files": [
    {
      "path": "src/auth/token.py",
      "include_mode": "full",
      "score": 120,
      "tokens": 450,
      "reasons": ["task keyword match", "related test"]
    }
  ],
  "skills": {
    "task_specific": [],
    "baseline": []
  },
  "skill_feedback": {
    "recent": [],
    "summary_by_skill": {}
  },
  "learning": {
    "artifacts": [],
    "latest_excerpt": ""
  },
  "benchmarks": {
    "latest": {},
    "averages": {}
  },
  "threads": {
    "active_count": 0,
    "conflicts": []
  },
  "suggested_actions": []
}
```

## Implementation Decisions

- Build a new `agentpack.dashboard` package with small modules for models, collection, rendering, and optional global registry.
- Keep `agentpack dashboard` as a normal Typer command module registered in `src/agentpack/cli.py`.
- Reuse existing helpers where possible:
  - `load_pack_metadata`
  - `task_freshness`
  - `list_thread_rows`
  - git helper functions
  - redaction helpers for bounded excerpts
- Use Pydantic models for the snapshot to make `--json` stable and testable.
- Render HTML with Python string/templates only for MVP. Do not add a frontend build chain.
- Use inline CSS only. Do not load remote assets, scripts, fonts, or CDNs.
- Keep MVP static and read-only. Use copyable commands for actions.
- Keep global dashboard behind a later phase so the first release does not require cross-project mutation from every command.

## Testing Decisions

Tests should verify external behavior and data contracts, not exact visual layout.

Test modules:

- `tests/test_dashboard_collectors.py`
- `tests/test_dashboard_renderer.py`
- `tests/test_dashboard_command.py`
- `tests/test_dashboard_global.py` when global phase starts

Test expectations:

- Missing files produce a valid snapshot and actionable empty states.
- Pack metadata produces overview, context, and selected-file rows.
- Skill feedback distinguishes recommended-only, used helpful, ignored, noisy, and bad recommendation states.
- Benchmark JSONL produces latest and average quality metrics.
- Static HTML contains key sections and no remote scripts.
- `--json` emits valid schema-versioned JSON.
- `--open` delegates to the platform opener without breaking generation.

## Privacy and Security

- The MVP must not make network calls.
- The static HTML must not reference remote JavaScript, CSS, images, fonts, or analytics.
- Bounded excerpts must be redacted before rendering.
- JSONL readers must cap rows, defaulting to the latest 500 records.
- The dashboard must not inline raw context files by default.
- Global learning promotion must be explicit in later phases.

## Out of Scope

- Hosted dashboard.
- Login, accounts, or telemetry.
- Full code editing.
- Automatic global lesson promotion.
- Database server.
- Frontend framework or bundler.
- Browser-side write actions in MVP.
- Team-shared dashboards without redaction.

## Success Metrics

- Users can run `agentpack dashboard` in an existing AgentPack project and get a useful HTML file without extra setup.
- Missing-data states suggest the next useful AgentPack command.
- The snapshot can be consumed with `agentpack dashboard --json`.
- Skill feedback state makes wrong recommendations visible instead of counting recommendations as correctness.
- The dashboard makes benchmark and learning artifacts discoverable from a single page.
- Existing `pytest -q` and docs link checks remain green.

## Rollout

Phase 1: Static project dashboard.

Phase 2: Global registry and static global dashboard.

Phase 3: Local server with actions.

Phase 4: Redacted team export and CI artifact mode.
