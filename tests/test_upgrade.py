from __future__ import annotations

from typer.testing import CliRunner

from agentpack.cli import app


def test_upgrade_auto_installs_codex_plugin_only_when_codex_detected(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_CODEX", "1")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    result = CliRunner().invoke(app, ["upgrade"])

    assert result.exit_code == 0, result.output
    assert "Auto-detected agent: codex" in result.output
    assert (tmp_path / "AGENTS.md").exists()
    assert list((tmp_path / "codex-home" / "plugins" / "cache" / "local" / "agentpack").glob("*/.codex-plugin/plugin.json"))


def test_upgrade_generic_does_not_install_codex_plugin(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    result = CliRunner().invoke(app, ["upgrade", "--agent", "generic"])

    assert result.exit_code == 0, result.output
    assert "Generic agent selected" in result.output
    assert not (tmp_path / "codex-home").exists()
