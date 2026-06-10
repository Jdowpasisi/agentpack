# Ralph Loop Protocol Design

## Purpose

AgentPack should support a Ralph Loop style autonomous development cycle without turning AgentPack into a coding agent. AgentPack should own orchestration, context freshness, progress memory, verification evidence, and completion gates. A configured external runner should own code generation.

The user-facing entry point should be an existing command:

```bash
agentpack work "task" --run
```

No new primary command is required for the MVP.

## Product Goals

- Make iterative agent work durable through local state files instead of chat memory.
- Keep every iteration grounded in fresh AgentPack context.
- Run a generic user-configured agent command, not a hardcoded Claude or Codex path.
- Enforce completion only at `agentpack finish`, so normal work remains low-friction.
- Stop safely on max iterations, repeated failures, missing runner config, or failed verification.
- Surface loop state in `agentpack next`, context packs, and the dashboard.

## Non-Goals

- No automatic push.
- No destructive git commands.
- No hosted service or remote telemetry.
- No automatic code review approval.
- No new autonomous-agent product boundary. AgentPack is the loop orchestrator.

## Configuration

New initialized repos should include:

```toml
[loop]
enabled = true
runner = ""
max_iterations = 10
verification_commands = []
require_verification = true
require_progress_update = true
require_clean_tree = true
auto_commit = false
auto_push = false
```

`runner` is empty by default. `agentpack work --run` must fail with a clear setup message until the user configures it or passes `--runner`.

`verification_commands` are explicit shell commands. If empty, `work --run` can still run iterations, but `finish` will not mark the loop complete when `require_verification = true`.

## State Files

AgentPack writes:

```text
.agentpack/loop_state.json
.agentpack/progress.md
.agentpack/loop_events.jsonl
.agentpack/loop_failures.jsonl
```

These are generated operational files and should be ignored by default.

`loop_state.json` contains:

- schema version
- enabled flag
- task text
- status: `idle`, `running`, `blocked`, `ready_to_finish`, `done`
- iteration count
- max iterations
- runner command
- verification commands
- last runner result
- last verification result
- repeated failure count
- started/updated timestamps
- finish blockers

`progress.md` contains a human-readable timeline and the current next action.

`loop_events.jsonl` records structured events for start, context refresh, runner result, verification result, blocked, ready, done.

`loop_failures.jsonl` records failed runner or verification attempts with bounded output excerpts.

## Command Integration

### `agentpack init`

Writes `[loop]` config defaults and ignores loop artifacts.

### `agentpack work --run`

Adds options:

```bash
agentpack work "task" --run
agentpack work "task" --run --dry-run
agentpack work "task" --run --runner "claude < .agentpack/context.claude.md"
agentpack work "task" --run --max-iterations 5
agentpack work "task" --run --verify "pytest -q" --verify "ruff check ."
```

Behavior:

1. Run existing `work` setup: init if needed, write task, refresh context, and show next steps unless suppressed.
2. Initialize loop state for the task.
3. On `--dry-run`, print the resolved loop plan and exit without running the runner.
4. For each iteration:
   - refresh context with existing pack/guard path
   - run the configured runner command
   - run configured verification commands
   - record events and bounded output excerpts
   - stop when verification passes
   - stop when max iterations is reached
   - stop when the same failure repeats too many times
5. If verification passes, mark loop status `ready_to_finish` and print `agentpack finish --since <ref>`.

### `agentpack pack`

Rendered context should include a bounded Ralph Loop section when loop state exists:

- loop status
- iteration count
- last verification status
- next required action
- finish blockers

### `agentpack next`

Adds recommendations when loop state exists:

- configure a runner
- run `agentpack work "..." --run`
- run verification commands
- run `agentpack finish`
- inspect loop failures

### `agentpack finish`

Enforces completion when `[loop].enabled = true` and a loop state exists for the current task.

`finish` fails if:

- context is stale
- loop status is not `ready_to_finish` or `done`
- verification is required but no verification passed
- progress update is required but no progress exists
- worktree is dirty and `require_clean_tree = true`

`finish` should print exact fix commands and not mutate state when blockers exist.

When checks pass, `finish` marks loop status `done` after the existing finish stages pass.

### `agentpack dashboard`

Adds a Ralph Loop panel:

- status
- iterations
- max iterations
- last runner result
- last verification result
- finish blockers
- suggested next command

## Safety Rules

- The runner command is never inferred from installed tools.
- Runner command uses the local shell because redirection and pipelines are core to generic runners.
- Output excerpts are bounded.
- Environment is inherited, but AgentPack does not print environment variables.
- No auto-push in MVP.
- `auto_commit` remains config-only and disabled in MVP behavior.
- Repeated same verification failure stops after three consecutive repeats.

## Testing Requirements

- Config defaults include `[loop]`.
- `init` ignores loop artifacts.
- `work --run --dry-run` writes loop state but does not execute runner.
- `work --run` fails clearly when no runner is configured.
- `work --run` executes a generic runner and verification command in a temp repo.
- Loop stops at max iterations.
- Loop stops on repeated verification failure.
- `finish` blocks when loop verification is missing.
- `finish` marks loop done when verification passed and existing finish stages pass.
- `next --json` includes loop recommendations.
- `dashboard` renders loop state.

## Rollout

Phase 1:

- config and ignored artifacts
- loop state model
- `work --run --dry-run`
- missing-runner failure

Phase 2:

- generic runner execution
- verification execution
- max iteration and repeated-failure stops

Phase 3:

- `finish` enforcement
- `next` recommendations
- dashboard panel

Phase 4:

- context-pack loop section
- optional auto-commit after green verification
