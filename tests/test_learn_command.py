from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess

from typer.testing import CliRunner

from agentpack.cli import app


runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _git_with_env(repo: Path, *args: str, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env={**os.environ, **env})


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("Add CLI learning summaries\n", encoding="utf-8")
    (tmp_path / "cli.py").write_text("import typer\n\napp = typer.Typer()\n", encoding="utf-8")
    _git(tmp_path, "add", ".agentpack/task.md", "cli.py")
    _git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "cli.py").write_text(
        "import typer\n\napp = typer.Typer()\n@app.command()\ndef learn():\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


def test_learn_writes_markdown_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0, result.output
    output = repo / ".agentpack" / "learning.md"
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "# AgentPack Learning Summary" in text
    assert "`cli.py`" in text


def test_learn_json_outputs_json_without_writing_default_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["task"] == "Add CLI learning summaries"
    assert payload["source_files"][0]["path"] == "cli.py"
    assert not (repo / ".agentpack" / "learning.md").exists()


def test_learn_custom_output_path(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--output", ".agentpack/custom.md"])

    assert result.exit_code == 0, result.output
    assert (repo / ".agentpack" / "custom.md").exists()


def test_learn_today_writes_daily_summary_path(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--today"])

    assert result.exit_code == 0, result.output
    output = repo / ".agentpack" / "daily-summary.md"
    assert output.exists()
    assert "**Scope:** today" in output.read_text(encoding="utf-8")


def test_learn_today_uses_calendar_day_commits(tmp_path, monkeypatch):
    repo = tmp_path
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".agentpack").mkdir()
    (repo / ".agentpack" / "task.md").write_text("Review today CLI work\n", encoding="utf-8")
    (repo / "old.py").write_text("print('old')\n", encoding="utf-8")
    _git(repo, "add", ".agentpack/task.md", "old.py")
    _git_with_env(
        repo,
        "commit",
        "-m",
        "old",
        env={"GIT_AUTHOR_DATE": "2020-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+0000"},
    )
    (repo / "new.py").write_text("import typer\napp = typer.Typer()\n", encoding="utf-8")
    _git(repo, "add", "new.py")
    _git(repo, "commit", "-m", "new")
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--today"])

    assert result.exit_code == 0, result.output
    text = (repo / ".agentpack" / "daily-summary.md").read_text(encoding="utf-8")
    assert "`new.py`" in text
    assert "`old.py`" not in text


def test_learn_updates_skill_map(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0, result.output
    payload = json.loads((repo / ".agentpack" / "skills-progress.json").read_text(encoding="utf-8"))
    assert payload["skills"]


def test_learn_writes_agent_lessons(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0, result.output
    text = (repo / ".agentpack" / "agent-lessons.md").read_text(encoding="utf-8")
    assert "# Agent Lessons" in text
    assert "Evidence:" in text


def test_learn_writes_llm_prompt_and_pr_comment(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--llm-prompt", "--pr-comment"])

    assert result.exit_code == 0, result.output
    prompt = (repo / ".agentpack" / "learning.prompt.md").read_text(encoding="utf-8")
    comment = (repo / ".agentpack" / "pr-learning-comment.md").read_text(encoding="utf-8")
    assert "source-backed learning summary" in prompt
    assert "## Learning Summary" in comment


def test_learn_records_feedback(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--feedback", "helpful", "--feedback-note", "Useful cards"])

    assert result.exit_code == 0, result.output
    lines = (repo / ".agentpack" / "learning-feedback.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["feedback"] == "helpful"
    assert payload["note"] == "Useful cards"
