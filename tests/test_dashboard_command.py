from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app


runner = CliRunner()


def test_dashboard_writes_project_html(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("fix auth\n", encoding="utf-8")

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / ".agentpack" / "dashboard.html").read_text(encoding="utf-8")
    assert "AgentPack Dashboard" in html
    assert "fix auth" in html


def test_dashboard_json_outputs_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    result = runner.invoke(app, ["dashboard", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["project"]["path"] == str(tmp_path)


def test_dashboard_writes_custom_output(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["dashboard", "--output", "out/dashboard.html"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "dashboard.html").exists()


def test_dashboard_open_writes_and_opens_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("agentpack.commands.dashboard._open_file", lambda path: opened.append(str(path)))

    result = runner.invoke(app, ["dashboard", "--open"])

    assert result.exit_code == 0, result.output
    dashboard = tmp_path / ".agentpack" / "dashboard.html"
    assert dashboard.exists()
    assert [str(Path(path).resolve()) for path in opened] == [str(dashboard)]
