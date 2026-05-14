from __future__ import annotations

from typer.testing import CliRunner

from agentpack.cli import app


def test_install_generic_is_supported_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["install", "--agent", "generic"])

    assert result.exit_code == 0, result.output
    assert "Generic agent selected" in result.output
    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()


def test_global_install_generic_is_supported_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["global-install", "--agent", "generic", "--dry-run", "--no-pipx", "--no-shell-hook", "--no-git-template"],
    )

    assert result.exit_code == 0, result.output
    assert "Generic agent selected" in result.output
