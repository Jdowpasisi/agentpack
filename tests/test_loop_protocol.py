from __future__ import annotations

from pathlib import Path

from agentpack.core.config import LoopConfig
from agentpack.core.loop_protocol import (
    LoopCommandResult,
    LoopRunnerContract,
    finish_blockers,
    initialize_loop,
    load_loop_state,
    mark_done,
    resolve_runner_adapter,
    run_loop,
    dry_run_plan,
)


def _ok(command: str = "ok") -> LoopCommandResult:
    return LoopCommandResult(command=command, returncode=0, output_excerpt="ok")


def _fail(command: str = "fail", output: str = "failed") -> LoopCommandResult:
    return LoopCommandResult(command=command, returncode=1, output_excerpt=output)


def test_initialize_loop_persists_state_and_progress(tmp_path: Path) -> None:
    cfg = LoopConfig(runner="python runner.py", verification_commands=["pytest -q"], acceptance_checks=["auth expiry fixed"])

    state = initialize_loop(tmp_path, "fix auth", cfg)

    assert state.task == "fix auth"
    assert state.runner == "python runner.py"
    assert state.verification_commands == ["pytest -q"]
    assert state.acceptance_checks == ["auth expiry fixed"]
    assert load_loop_state(tmp_path).task == "fix auth"
    assert (tmp_path / ".agentpack" / "progress.md").read_text(encoding="utf-8").startswith("# AgentPack Ralph Loop Progress")
    assert "auth expiry fixed" in (tmp_path / ".agentpack" / "loop_runner_prompt.md").read_text(encoding="utf-8")


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
    assert (tmp_path / ".agentpack" / "loop_diagnosis.md").exists()


def test_run_loop_records_structured_runner_contract(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    runner_payload = '{"status":"changed","summary":"patched auth","files_changed":["auth.py"],"acceptance":{"auth fixed":"pass"}}'

    summary = run_loop(
        tmp_path,
        state,
        refresh=lambda: _ok("refresh"),
        run_command=lambda command, timeout_seconds: LoopCommandResult(
            command=command,
            returncode=0,
            output_excerpt=runner_payload if command == "agent" else "ok",
        ),
    )

    updated = load_loop_state(tmp_path)
    assert summary.status == "ready_to_finish"
    assert updated.last_runner_contract.status == "changed"
    assert updated.last_runner_contract.files_changed == ["auth.py"]
    assert updated.last_runner_contract.acceptance == {"auth fixed": "pass"}


def test_resolve_runner_adapter_returns_empty_when_binary_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentpack.core.loop_protocol.shutil.which", lambda name: None)

    assert resolve_runner_adapter("claude", tmp_path) == ""


def test_run_loop_blocks_on_runner_contract_blocked(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))

    summary = run_loop(
        tmp_path,
        state,
        refresh=lambda: _ok("refresh"),
        run_command=lambda command, timeout_seconds: LoopCommandResult(
            command=command,
            returncode=0,
            output_excerpt='{"status":"blocked","blocker":"missing credentials"}',
        ),
    )

    assert summary.status == "blocked"
    assert summary.reason == "runner_blocked"
    assert "missing credentials" in (tmp_path / ".agentpack" / "loop_diagnosis.md").read_text(encoding="utf-8")
    handoff = (tmp_path / ".agentpack" / "loop_handoff.md").read_text(encoding="utf-8")
    assert "missing credentials" in handoff


def test_run_loop_blocks_on_runner_contract_no_change(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))

    summary = run_loop(
        tmp_path,
        state,
        refresh=lambda: _ok("refresh"),
        run_command=lambda command, timeout_seconds: LoopCommandResult(
            command=command,
            returncode=0,
            output_excerpt='{"status":"no_change","summary":"nothing to edit"}',
        ),
    )

    assert summary.status == "blocked"
    assert summary.reason == "no_diff_change"


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
    updated = load_loop_state(tmp_path)
    assert updated.repeated_failure_count == 2
    assert updated.failure_class == "unknown"


def test_run_loop_blocks_when_failure_repeats_without_diff_change(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    state = initialize_loop(
        tmp_path,
        "fix auth",
        LoopConfig(runner="agent", verification_commands=["pytest -q"], max_iterations=5, max_repeated_failures=5),
    )

    def run_command(command: str, timeout_seconds: int) -> LoopCommandResult:
        if command == "agent":
            (tmp_path / "app.py").write_text("value = 2\n", encoding="utf-8")
            return _ok(command)
        return _fail(command, "same failure")

    summary = run_loop(tmp_path, state, refresh=lambda: _ok("refresh"), run_command=run_command)

    assert summary.status == "blocked"
    assert summary.reason == "no_diff_change"


def test_run_loop_executes_shell_runner_in_repo_root(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "runner.py").write_text(
        "from pathlib import Path\nPath('app.py').write_text('value = 2\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    state = initialize_loop(tmp_path, "fix app", LoopConfig(runner="python runner.py", verification_commands=["python -c 'import app; assert app.value == 2'"]))

    summary = run_loop(tmp_path, state, refresh=lambda: _ok("refresh"))

    updated = load_loop_state(tmp_path)
    assert summary.status == "ready_to_finish"
    assert updated.acceptance_file == ".agentpack/loop_acceptance.md"
    assert updated.risk_review_file == ".agentpack/loop_risk_review.md"
    assert "app.py" in updated.last_diff.files_changed


def test_finish_blockers_require_ready_state_and_verification(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))

    blockers = finish_blockers(tmp_path, LoopConfig(), state)

    assert any(blocker.kind == "loop_not_ready" for blocker in blockers)
    assert any(blocker.command == 'agentpack work "fix auth" --run' for blocker in blockers)


def test_finish_blockers_require_diff_unless_allowed(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")

    blockers = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state)
    allowed = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state, allow_empty_diff=True)

    assert any(blocker.kind == "empty_loop_diff" for blocker in blockers)
    assert any(blocker.kind == "acceptance_missing" for blocker in blockers)
    assert not any(blocker.kind == "empty_loop_diff" for blocker in allowed)


def test_finish_blockers_require_configured_acceptance_checks(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"], acceptance_checks=["auth fixed"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")
    state.acceptance_file = ".agentpack/loop_acceptance.md"
    state.last_diff.changed = True

    missing = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state)
    state.last_runner_contract = LoopRunnerContract(status="changed", acceptance={"auth fixed": "pass"})
    passed = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state)

    assert any(blocker.kind == "acceptance_checks_missing" for blocker in missing)
    assert not any(blocker.kind == "acceptance_checks_missing" for blocker in passed)


def test_finish_blockers_block_high_risk_diff(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")
    state.acceptance_file = ".agentpack/loop_acceptance.md"
    state.last_diff.changed = True
    state.last_diff.files_changed = ["src/auth.py"]
    state.risk_review.level = "high"

    blockers = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state)
    allowed = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state, allow_high_risk=True)

    assert any(blocker.kind == "high_risk_diff" for blocker in blockers)
    assert not any(blocker.kind == "high_risk_diff" for blocker in allowed)


def test_configured_sensitive_glob_marks_high_risk(tmp_path: Path) -> None:
    state = initialize_loop(
        tmp_path,
        "fix api",
        LoopConfig(runner="agent", verification_commands=["pytest -q"], risk_sensitive_globs=["src/public_api/**"]),
    )
    state.last_diff.files_changed = ["src/public_api/routes.py"]

    # Exercise private review helper via run loop path by setting snapshot then checking risk on ready state.
    from agentpack.core.loop_protocol import _review_loop_risk

    risk = _review_loop_risk(state)

    assert risk.level == "high"
    assert "configured sensitive path changed" in risk.reasons


def test_finish_blockers_ignore_dirty_baseline_without_post_run_change(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "existing.txt").write_text("dirty before loop\n", encoding="utf-8")
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")

    blockers = finish_blockers(tmp_path, LoopConfig(require_clean_tree=False), state)

    assert any(blocker.kind == "empty_loop_diff" for blocker in blockers)


def test_mark_done_updates_state(tmp_path: Path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = _ok("pytest -q")
    state.progress_updates = 1

    mark_done(tmp_path, "Finished")

    updated = load_loop_state(tmp_path)
    assert updated.status == "done"
    assert updated.finish_summary == "Finished"
