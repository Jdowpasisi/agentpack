from __future__ import annotations

import subprocess

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


def test_pack_auto_repairs_stale_agent_rule_block(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("Pack should self-heal stale codex rule\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "<!-- agentpack:start -->\n"
        "Old AgentPack instructions: run agentpack pack --task auto and read context.md\n"
        "<!-- agentpack:end -->\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["pack", "--agent", "codex"])

    assert result.exit_code == 0, result.output
    assert "Auto-repaired stale AgentPack integration for codex" in result.output
    assert "agentpack guard --agent codex --repair-stale --refresh-context" in (
        tmp_path / "AGENTS.md"
    ).read_text(encoding="utf-8")
