from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app


def test_dev_check_json_orchestrates_stages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return Result()

    monkeypatch.setattr("agentpack.commands.dev_check.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["dev-check", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert [stage["name"] for stage in payload["stages"]] == ["docs-check", "ruff", "pytest", "npm-version-sync", "npm-launcher"]
    assert calls


def test_verify_wheel_json_uses_existing_wheel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    wheel = tmp_path / "dist" / "agentpack_cli-1.0.0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_text("wheel", encoding="utf-8")

    monkeypatch.setattr(
        "agentpack.commands.verify_wheel._run",
        lambda _root, name, command: {"name": name, "command": " ".join(command), "returncode": 0, "detail": "ok"},
    )

    result = CliRunner().invoke(app, ["verify-wheel", "--skip-build", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["wheel"].endswith(".whl")


def test_release_prepare_json_orchestrates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("agentpack.commands.release_cmd.subprocess.run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(
        "agentpack.commands.release_cmd.run_verify_wheel",
        lambda: {"passed": True, "stages": [{"name": "build", "command": "python -m build", "returncode": 0, "detail": ""}]},
    )

    result = CliRunner().invoke(app, ["release", "prepare", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert [stage["name"] for stage in payload["stages"]] == ["release-check", "benchmark-public-table", "verify-wheel:build"]
