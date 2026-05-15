from __future__ import annotations

from typer.testing import CliRunner

from agentpack.cli import app


def test_pack_rejects_explicit_task_text(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["pack", "--agent", "generic", "--task", "fix auth bug"])

    assert result.exit_code == 2
    assert "no longer supported" in result.output
    assert ".agentpack/task.md" in result.output
    assert "agentpack pack --task auto" in result.output


def test_pack_help_directs_tasks_to_task_md() -> None:
    result = CliRunner().invoke(app, ["pack", "--help"])

    assert result.exit_code == 0
    assert "Only 'auto' is supported" in result.output
    assert ".agentpack/task.md" in result.output
