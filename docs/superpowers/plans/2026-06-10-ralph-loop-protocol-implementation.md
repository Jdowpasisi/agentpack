# Ralph Loop Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-enabled Ralph Loop protocol that can run a generic external agent through `agentpack work "task" --run`, persist loop state, verify iterations, enforce completion at `finish`, and expose state through `next` and the dashboard.

**Architecture:** Add a focused `agentpack.core.loop_protocol` module for config-driven state, events, runner execution, verification, and finish blockers. Wire existing commands rather than adding a new primary command: `init`, `work`, `finish`, `next`, and `dashboard`.

**Tech Stack:** Python 3.10+, Typer, Pydantic config, pathlib, JSON/JSONL, subprocess, pytest.

---

## File Structure

- Modify `src/agentpack/core/config.py`
  - Add `LoopConfig` defaults and `[loop]` config template.
- Modify `src/agentpack/commands/init.py`
  - Ignore generated loop artifacts in root and `.agentpack/.gitignore`.
- Create `src/agentpack/core/loop_protocol.py`
  - Own loop state files, events, runner execution, verification, dry-run planning, and finish blockers.
- Modify `src/agentpack/commands/workflow_cmd.py`
  - Add `work --run`, `--dry-run`, `--runner`, `--max-iterations`, and repeatable `--verify`.
  - Add finish enforcement before existing finish mutation stages, and mark loop done after successful finish.
- Modify `src/agentpack/commands/next_cmd.py`
  - Add loop recommendations.
- Modify `src/agentpack/dashboard/models.py`
  - Add `LoopSummary`.
- Modify `src/agentpack/dashboard/collectors.py`
  - Load loop state into dashboard snapshot.
- Modify `src/agentpack/dashboard/renderers.py`
  - Render Ralph Loop panel.
- Create `tests/test_loop_protocol.py`
  - Unit-test state, dry-run planning, runner verification, max iteration, repeated failure, and finish blockers.
- Modify `tests/test_init.py`
  - Assert loop artifacts are ignored.
- Modify `tests/test_workflow_automation.py`
  - Test `work --run` surfaces through the real CLI.
- Modify `tests/test_dashboard_renderer.py`
  - Test loop state rendering.
- Modify `tests/test_dashboard_collectors.py`
  - Test loop state collection.
- Modify `tests/test_next_command.py`
  - Test loop recommendations.

## Tasks

### Task 1: Config and Ignored Artifacts

- [ ] Add `LoopConfig` to `src/agentpack/core/config.py` with:
  - `enabled = True`
  - `runner = ""`
  - `max_iterations = 10`
  - `verification_commands = []`
  - `require_verification = True`
  - `require_progress_update = True`
  - `require_clean_tree = True`
  - `auto_commit = False`
  - `auto_push = False`
  - `runner_timeout_seconds = 600`
  - `verification_timeout_seconds = 600`
  - `max_repeated_failures = 3`
- [ ] Add `[loop]` to `CONFIG_TEMPLATE`.
- [ ] Add loop artifact ignores to `src/agentpack/commands/init.py`.
- [ ] Update `tests/test_init.py`.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_init.py -q`.
- [ ] Commit `feat: add loop config defaults`.

### Task 2: Loop Protocol Core

- [ ] Create `src/agentpack/core/loop_protocol.py`.
- [ ] Implement:
  - `LoopState`
  - `LoopCommandResult`
  - `LoopRunSummary`
  - `LoopPlan`
  - `load_loop_state(root)`
  - `save_loop_state(root, state)`
  - `initialize_loop(root, task, cfg, runner_override, max_iterations_override, verification_overrides)`
  - `dry_run_plan(root, state)`
  - `run_loop(root, state, refresh, run_command)`
  - `finish_blockers(root, cfg, state)`
  - `mark_done(root, summary)`
- [ ] Use bounded output excerpts of 4000 characters.
- [ ] Stop after `max_iterations`.
- [ ] Stop after `max_repeated_failures` identical verification failures.
- [ ] Update `progress.md`, `loop_events.jsonl`, and `loop_failures.jsonl`.
- [ ] Add `tests/test_loop_protocol.py`.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_loop_protocol.py -q`.
- [ ] Commit `feat: add ralph loop protocol core`.

### Task 3: `work --run`

- [ ] Modify `src/agentpack/commands/workflow_cmd.py`.
- [ ] Add `work` options:
  - `--run`
  - `--dry-run`
  - `--runner`
  - `--max-iterations`
  - repeatable `--verify`
- [ ] Existing `work` behavior remains unchanged unless `--run` or `--dry-run` is present.
- [ ] For `--dry-run`, run existing start flow, initialize loop state, print JSON-like plan, and do not execute runner.
- [ ] For `--run`, fail clearly when runner is missing.
- [ ] For `--run`, refresh context per iteration with `run_refresh`, execute runner command, execute verification commands, and print final status.
- [ ] Add/modify CLI tests in `tests/test_workflow_automation.py`.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_workflow_automation.py tests/test_loop_protocol.py -q`.
- [ ] Commit `feat: run generic ralph loop from work`.

### Task 4: Finish Enforcement

- [ ] In `src/agentpack/commands/workflow_cmd.py`, before existing finish stages, load loop config and state.
- [ ] If loop is enabled and state task matches current finish task, call `finish_blockers`.
- [ ] If blockers exist, print exact fix commands and exit non-zero without mutating state.
- [ ] After existing finish stages pass, mark loop done.
- [ ] Add tests for blocked and passing finish flows.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_workflow_automation.py tests/test_loop_protocol.py -q`.
- [ ] Commit `feat: enforce ralph loop completion`.

### Task 5: `next` and Dashboard Visibility

- [ ] Add loop recommendations to `src/agentpack/commands/next_cmd.py`.
- [ ] Add `LoopSummary` to dashboard models.
- [ ] Collect loop summary from `.agentpack/loop_state.json`.
- [ ] Render a Ralph Loop panel in dashboard HTML.
- [ ] Add tests for next recommendations and dashboard rendering/collection.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_next_command.py tests/test_dashboard_collectors.py tests/test_dashboard_renderer.py tests/test_dashboard_command.py -q`.
- [ ] Commit `feat: surface ralph loop state`.

### Task 6: Final Verification

- [ ] Run `python -m ruff check src/agentpack/core/loop_protocol.py src/agentpack/commands/workflow_cmd.py src/agentpack/commands/next_cmd.py src/agentpack/dashboard tests/test_loop_protocol.py tests/test_workflow_automation.py tests/test_dashboard_*.py`.
- [ ] Run `PYTHONPATH=src python -m pytest -q`.
- [ ] Run `PYTHONPATH=src python -m agentpack.cli work "loop smoke" --run --dry-run --runner "python -c 'print(123)'" --verify "python -c 'print(456)'"`.
- [ ] Run `PYTHONPATH=src python -m agentpack.cli dashboard`.
- [ ] Check generated dashboard has no `http://`, `https://`, or `<script`.
- [ ] Commit any final fixes.
- [ ] Push branch.

## Scope Boundaries

This MVP does not implement auto-commit, auto-push, hosted telemetry, or hardcoded Claude/Codex runner presets.
