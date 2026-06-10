from __future__ import annotations

import json

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.config import LoopConfig
from agentpack.core.loop_protocol import initialize_loop


def test_next_recommends_loop_runner_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("[context]\n", encoding="utf-8")
    (tmp_path / ".agentpack" / "task.md").write_text("fix auth\n", encoding="utf-8")
    initialize_loop(tmp_path, "fix auth", LoopConfig(runner="", verification_commands=["pytest -q"]))
    monkeypatch.setattr("agentpack.commands.next_cmd._context_is_fresh", lambda _root: (True, "fresh"))

    result = CliRunner().invoke(app, ["next", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(item["kind"] == "loop_runner_missing" for item in payload["recommendations"])
