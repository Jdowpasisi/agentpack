from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app


def test_work_initializes_starts_and_runs_next(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        if "init" in command:
            (tmp_path / ".agentpack").mkdir()
            (tmp_path / ".agentpack" / "config.toml").write_text("[context]\n", encoding="utf-8")
        return Result()

    monkeypatch.setattr("agentpack.commands.workflow_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["work", "fix auth", "--thread", "codex-local", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert [stage["name"] for stage in payload["stages"]] == ["init", "start", "next"]
    assert any("start" in call for call in calls)


def test_finish_runs_diagnosis_capture_checks_done_and_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack" / "threads" / "codex-local").mkdir(parents=True)
    (tmp_path / ".agentpack" / "threads" / "codex-local" / "task.md").write_text("fix auth\n", encoding="utf-8")
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return Result()

    monkeypatch.setattr("agentpack.commands.workflow_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["finish", "--since", "main", "--thread", "codex-local", "--archive-thread", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert [stage["name"] for stage in payload["stages"]] == [
        "diagnose-selection",
        "benchmark-capture",
        "dev-check",
        "state-done",
        "threads-archive",
    ]
    assert any(call[:3] == [call[0], "-m", "agentpack.cli"] for call in calls)


def test_ci_init_writes_workflow_and_refuses_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["ci", "init", "--json"])
    second = runner.invoke(app, ["ci", "init", "--json"])

    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["written"] is True
    assert (tmp_path / ".github" / "workflows" / "agentpack.yml").exists()
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["written"] is False


def test_next_fix_all_safe_initializes_and_writes_diagnosis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        (tmp_path / ".agentpack").mkdir(exist_ok=True)
        (tmp_path / ".agentpack" / "config.toml").write_text("[context]\n", encoding="utf-8")
        return Result()

    monkeypatch.setattr("agentpack.commands.next_cmd.subprocess.run", fake_run)
    monkeypatch.setattr("agentpack.commands.next_cmd._context_is_fresh", lambda _root: (True, "fresh"))

    result = CliRunner().invoke(app, ["next", "--fix-all-safe", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["fixes"][0]["kind"] == "init"
