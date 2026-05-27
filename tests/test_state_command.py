from __future__ import annotations

import json

from typer.testing import CliRunner

from agentpack.cli import app


def test_state_set_and_show_global_preserves_checklist(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task_state.md").write_text("Status: planned\nSummary: old\n- [ ] keep this\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["state", "set", "blocked", "--summary", "Waiting"])
    shown = CliRunner().invoke(app, ["state", "show", "--json"])

    assert result.exit_code == 0
    payload = json.loads(shown.output)
    assert payload["task"]["status"] == "blocked"
    assert payload["task"]["summary"] == "Waiting"
    assert payload["task"]["checklist"]["open"] == 1


def test_state_done_writes_scoped_state(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["state", "done", "--thread", "codex/local", "--summary", "Finished"])

    assert result.exit_code == 0
    path = tmp_path / ".agentpack" / "threads" / "codex-local" / "task_state.md"
    assert "Status: done" in path.read_text(encoding="utf-8")
    assert "Summary: Finished" in path.read_text(encoding="utf-8")
