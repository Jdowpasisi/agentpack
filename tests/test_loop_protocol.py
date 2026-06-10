from __future__ import annotations

from pathlib import Path

from agentpack.core.config import LoopConfig
from agentpack.core.loop_protocol import (
    LoopCommandResult,
    finish_blockers,
    initialize_loop,
    load_loop_state,
    mark_done,
    run_loop,
    dry_run_plan,
)


def _ok(command: str = "ok") -> LoopCommandResult:
    return LoopCommandResult(command=command, returncode=0, output_excerpt="ok")


def _fail(command: str = "fail", output: str = "failed") -> LoopCommandResult:
    return LoopCommandResult(command=command, returncode=1, output_excerpt=output)


def test_initialize_loop_persists_state_and_progress(tmp_path: Path) -> None:
    cfg = LoopConfig(runner="python runner.py", verification_commands=["pytest -q"])

    state = initialize_loop(tmp_path, "fix auth", cfg)

    assert state.task == "fix auth"
    assert state.runner == "python runner.py"
    assert state.verification_commands == ["pytest -q"]
    assert load_loop_state(tmp_path).task == "fix auth"
    assert (tmp_path / ".agentpack" / "progress.md").read_text(encoding="utf-8").startswith("# AgentPack Ralph Loop Progress")


def test_dry_run_plan_reports_runner_and_verification(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))

    plan = dry_run_plan(tmp_path, state)

    assert plan.task == "fix auth"
    assert plan.runner == "agent"
    assert plan.verification_commands == ["pytest -q"]
    assert plan.max_iterations == 10


def test_run_loop_reaches_ready_to_finish_after_verification_passes(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    calls: list[str] = []

    def run_command(command: str, timeout_seconds: int) -> LoopCommandResult:
        calls.append(command)
        return _ok(command)

    summary = run_loop(tmp_path, state, refresh=lambda: _ok("refresh"), run_command=run_command)

    assert summary.status == "ready_to_finish"
    assert calls == ["agent", "pytest -q"]
    assert load_loop_state(tmp_path).status == "ready_to_finish"


def test_run_loop_stops_at_max_iterations(tmp_path: Path) -> None:
    state = initialize_loop(
        tmp_path,
        "fix auth",
        LoopConfig(runner="agent", verification_commands=["pytest -q"], max_iterations=2, max_repeated_failures=5),
    )

    summary = run_loop(
        tmp_path,
        state,
        refresh=lambda: _ok("refresh"),
        run_command=lambda command, timeout_seconds: _ok(command) if command == "agent" else _fail(command, f"fail {timeout_seconds}"),
    )

    assert summary.status == "blocked"
    assert summary.reason == "max_iterations_reached"
    assert load_loop_state(tmp_path).iteration == 2


def test_run_loop_stops_on_repeated_verification_failure(tmp_path: Path) -> None:
    state = initialize_loop(
        tmp_path,
        "fix auth",
        LoopConfig(runner="agent", verification_commands=["pytest -q"], max_iterations=10, max_repeated_failures=2),
    )

    summary = run_loop(
        tmp_path,
        state,
        refresh=lambda: _ok("refresh"),
        run_command=lambda command, timeout_seconds: _ok(command) if command == "agent" else _fail(command, "same failure"),
    )

    assert summary.status == "blocked"
    assert summary.reason == "repeated_verification_failure"
    assert load_loop_state(tmp_path).repeated_failure_count == 2


def test_finish_blockers_require_ready_state_and_verification(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))

    blockers = finish_blockers(tmp_path, LoopConfig(), state)

    assert any(blocker.kind == "loop_not_ready" for blocker in blockers)
    assert any(blocker.command == 'agentpack work "fix auth" --run' for blocker in blockers)


def test_mark_done_updates_state(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")
    state.progress_updates = 1

    mark_done(tmp_path, "Finished")

    updated = load_loop_state(tmp_path)
    assert updated.status == "done"
    assert updated.finish_summary == "Finished"
