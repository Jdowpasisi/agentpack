from __future__ import annotations

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.integrations.global_install import _AGENTPACK_MARKER, _HOOK_SCRIPTS, _SHELL_MARKER_END, _SHELL_MARKER_START


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


def test_upgrade_refreshes_existing_global_hooks_without_manual_repair(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import agentpack.integrations.global_install as global_install

    template_dir = tmp_path / ".git-templates"
    monkeypatch.setattr(global_install, "_GIT_TEMPLATE_DIR", template_dir)
    hooks_dir = template_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    legacy = (
        "#!/bin/sh\n"
        f"{_AGENTPACK_MARKER}\n"
        "[ -f .agentpack/config.toml ] && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &\n"
    )
    for name in _HOOK_SCRIPTS:
        (hooks_dir / name).write_text(legacy, encoding="utf-8")

    rc = tmp_path / ".zshrc"
    rc.write_text(
        f"# before\n{_SHELL_MARKER_START}\nold shell hook\n{_SHELL_MARKER_END}\n# after\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(global_install, "_detect_rc_file", lambda: rc)
    monkeypatch.setattr(global_install, "configure_git_template_dir", lambda dry_run=False: "configured")

    result = CliRunner().invoke(app, ["upgrade", "--agent", "generic"])

    assert result.exit_code == 0, result.output
    assert "Refreshing existing global git template hooks" in result.output
    assert "Refreshing existing shell cd hook" in result.output
    for name in _HOOK_SCRIPTS:
        content = (hooks_dir / name).read_text(encoding="utf-8")
        assert "GitAutoRepack" in content
        assert "[ -f .agentpack/config.toml ]" not in content
    shell_content = rc.read_text(encoding="utf-8")
    assert "old shell hook" not in shell_content
    assert "_agentpack_chpwd" in shell_content


def test_upgrade_does_not_create_new_global_hooks_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import agentpack.integrations.global_install as global_install

    template_dir = tmp_path / ".git-templates"
    rc = tmp_path / ".zshrc"
    rc.write_text("# user shell config\n", encoding="utf-8")
    monkeypatch.setattr(global_install, "_GIT_TEMPLATE_DIR", template_dir)
    monkeypatch.setattr(global_install, "_detect_rc_file", lambda: rc)

    class Result:
        stdout = ""

    monkeypatch.setattr("agentpack.commands.upgrade.subprocess.run", lambda *args, **kwargs: Result())

    result = CliRunner().invoke(app, ["upgrade", "--agent", "generic"])

    assert result.exit_code == 0, result.output
    assert "No existing global AgentPack hooks found to refresh" in result.output
    assert not template_dir.exists()
    assert rc.read_text(encoding="utf-8") == "# user shell config\n"
