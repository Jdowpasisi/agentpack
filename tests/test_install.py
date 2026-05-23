from __future__ import annotations

import agentpack.integrations.global_install as gi
from typer.testing import CliRunner

from agentpack.cli import app


def test_install_generic_is_supported_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["install", "--agent", "generic"])

    assert result.exit_code == 0, result.output
    assert "No agent-specific hooks" in result.output
    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()


def test_global_install_generic_is_supported_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["global-install", "--agent", "generic", "--dry-run", "--no-pipx", "--no-shell-hook", "--no-git-template"],
    )

    assert result.exit_code == 0, result.output
    assert "generic has no agent-specific hooks" in result.output


def test_global_repair_hooks_repairs_templates_and_repo_hooks(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
    monkeypatch.setattr("agentpack.commands.install.configure_git_template_dir", lambda dry_run=False: "configured")
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    legacy = "#!/bin/sh\n# agentpack:global\n[ -f .agentpack/config.toml ] && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &\n"
    for name in ("post-checkout", "post-commit", "post-merge"):
        (tmp_path / ".git-templates" / "hooks").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".git-templates" / "hooks" / name).write_text(legacy, encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["global-repair-hooks"])

    assert result.exit_code == 0, result.output
    assert "Hook repair complete." in result.output
    assert ".git/hooks/post-commit" in result.output
    hook = tmp_path / ".git-templates" / "hooks" / "post-checkout"
    assert hook.exists()
    assert hook.read_text(encoding="utf-8").rstrip().endswith("exit 0")
    repo_hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert repo_hook.exists()
    assert "GitAutoRepack" in repo_hook.read_text(encoding="utf-8")


def test_global_repair_hooks_without_repo_hooks_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
    monkeypatch.setattr("agentpack.commands.install.configure_git_template_dir", lambda dry_run=False: "configured")
    runner = CliRunner()

    result = runner.invoke(app, ["global-repair-hooks"])

    assert result.exit_code == 0, result.output
    assert "No local .git/hooks directory found" in result.output
