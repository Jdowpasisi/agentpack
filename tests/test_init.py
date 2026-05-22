from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.commands.init import _patch_agentignore, _patch_repo_gitignore, _repo_gitignore_block


def test_repo_gitignore_block_ignores_generated_artifacts() -> None:
    block = _repo_gitignore_block()
    lines = block.splitlines()

    assert ".agentpack/*" in lines
    assert "!.agentpack/config.toml" in lines
    assert ".agentignore" in lines
    assert ".agentpack/cache/" in lines
    assert ".agentpack/context*" in lines
    assert ".agentpack/.gitignore" in lines
    assert ".agentpack/.mcp_reminded" in lines
    assert ".agentpack/session.json" in lines
    assert ".agentpack/task.md" in lines
    assert ".agent/skills/agentpack/" not in lines
    assert ".vscode/tasks.json" not in lines
    assert "GEMINI.md" not in lines


def test_repo_gitignore_block_adds_agent_specific_entries() -> None:
    antigravity = _repo_gitignore_block(agent="antigravity").splitlines()
    cursor = _repo_gitignore_block(agent="cursor").splitlines()

    assert ".agent/skills/agentpack/" in antigravity
    assert ".vscode/tasks.json" in antigravity
    assert "GEMINI.md" in antigravity
    assert ".vscode/tasks.json" in cursor
    assert "GEMINI.md" not in cursor


def test_repo_gitignore_block_respects_share_cache() -> None:
    lines = _repo_gitignore_block(share_cache=True).splitlines()

    assert ".agentpack/cache/" not in lines
    assert "!.agentpack/cache/" in lines
    assert "!.agentpack/cache/**" in lines
    assert ".agentpack/snapshots/" in lines


def test_patch_repo_gitignore_appends_idempotently(tmp_path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("dist/\n", encoding="utf-8")

    assert _patch_repo_gitignore(tmp_path) == "updated"
    first = gitignore.read_text(encoding="utf-8")
    assert "dist/" in first
    assert first.count("# agentpack:start") == 1

    assert _patch_repo_gitignore(tmp_path) == "unchanged"
    second = gitignore.read_text(encoding="utf-8")
    assert second == first


def test_patch_repo_gitignore_updates_existing_block_for_share_cache(tmp_path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(_repo_gitignore_block(share_cache=False), encoding="utf-8")

    assert _patch_repo_gitignore(tmp_path, share_cache=True) == "updated"
    content = gitignore.read_text(encoding="utf-8")

    lines = content.splitlines()

    assert ".agentpack/cache/" not in lines
    assert "!.agentpack/cache/" in lines
    assert content.count("# agentpack:start") == 1


def test_patch_agentignore_imports_safe_root_gitignore_rules(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            [
                "dist/",
                "backend/.serverless/",
                "*.snap",
                "!dist/keep.txt",
                "docs/",
                "src/generated/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    action, status = _patch_agentignore(tmp_path)
    assert action == "created"
    assert status.imported_rules
    content = (tmp_path / ".agentignore").read_text(encoding="utf-8")

    assert "dist/" in content
    assert "backend/.serverless/" in content
    assert "*.snap" in content
    assert "!dist/keep.txt" not in content
    assert "\ndocs/\n" not in content
    assert "src/generated/" in content
    assert "# agentpack:imported-gitignore:start" in content


def test_patch_agentignore_updates_import_block_idempotently(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")
    (tmp_path / ".agentignore").write_text("custom-rule/\n", encoding="utf-8")

    action, _status = _patch_agentignore(tmp_path)
    assert action == "updated"
    first = (tmp_path / ".agentignore").read_text(encoding="utf-8")
    assert "custom-rule/" in first
    assert "backend/.serverless/" in first

    action, _status = _patch_agentignore(tmp_path)
    assert action == "unchanged"
    second = (tmp_path / ".agentignore").read_text(encoding="utf-8")
    assert second == first


def test_init_writes_repo_gitignore_block(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".agentpack/context*" in content
    assert ".agentpack/*" in content
    assert "!.agentpack/config.toml" in content
    assert ".agentignore" in content
    assert ".agentpack/task.md" in content
    assert ".vscode/tasks.json" not in content
    assert "GEMINI.md" not in content


def test_init_writes_agent_specific_gitignore_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--agent", "antigravity"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".agent/skills/agentpack/" in content
    assert ".vscode/tasks.json" in content
    assert "GEMINI.md" in content


def test_init_share_cache_unignores_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--share-cache"])

    assert result.exit_code == 0, result.output
    repo_lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    agentpack_lines = (tmp_path / ".agentpack" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".agentpack/cache/" not in repo_lines
    assert "!.agentpack/cache/" in repo_lines
    assert "!.agentpack/cache/**" in repo_lines
    assert "cache/" not in agentpack_lines


def test_init_imports_safe_gitignore_rules_into_agentignore(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".gitignore").write_text("dist/\ndocs/\nbackend/.serverless/\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".agentignore").read_text(encoding="utf-8")
    assert "dist/" in content
    assert "backend/.serverless/" in content
    assert "\ndocs/\n" not in content


def test_init_dry_run_does_not_write_files(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--dry-run", "--agent", "codex"])

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "AGENTS.md" in result.output
    assert not (tmp_path / ".agentpack").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_init_rejects_invalid_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--mode", "banana"])

    assert result.exit_code == 1
    assert "Unknown mode" in result.output


def test_init_force_backs_up_existing_files(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".gitignore").write_text(".serverless/\n", encoding="utf-8")
    (tmp_path / ".agentpack" / "config.toml").write_text("old config\n", encoding="utf-8")
    (tmp_path / ".agentignore").write_text("old ignore\n", encoding="utf-8")
    (tmp_path / "GEMINI.md").write_text("old gemini\n", encoding="utf-8")
    (tmp_path / ".vscode" / "tasks.json").write_text('{"version":"2.0.0","tasks":[]}\n', encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--force", "--agent", "antigravity"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".agentpack" / "config.toml.bak").read_text(encoding="utf-8") == "old config\n"
    assert (tmp_path / ".agentignore.bak").read_text(encoding="utf-8") == "old ignore\n"
    assert (tmp_path / "GEMINI.md.bak").read_text(encoding="utf-8") == "old gemini\n"
    assert (tmp_path / ".vscode" / "tasks.json.bak").exists()
    assert "Backups" in result.output


@pytest.mark.parametrize(
    ("agent", "expected_files", "expected_git_hooks"),
    [
        ("claude", ("CLAUDE.md", ".claude/settings.json", ".mcp.json"), False),
        ("cursor", (".cursorrules", ".cursor/rules/agentpack.mdc", ".vscode/tasks.json"), True),
        ("windsurf", (".windsurfrules", ".vscode/tasks.json"), True),
        ("codex", ("AGENTS.md", ".codex/hooks.json"), True),
        ("antigravity", ("GEMINI.md", ".vscode/tasks.json"), True),
    ],
)
def test_init_installs_agent_integrations(tmp_path, monkeypatch, agent, expected_files, expected_git_hooks) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes", "--agent", agent])

    assert result.exit_code == 0, result.output
    for path in expected_files:
        assert path in result.output
        assert (tmp_path / path).exists()
    if agent == "claude":
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "agentpack hook --event SessionStart" in json.dumps(settings)
        assert "agentpack hook --event UserPromptSubmit" in json.dumps(settings)
        mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
        assert mcp["mcpServers"]["agentpack"] == {"command": "agentpack", "args": ["mcp"]}
    if not expected_git_hooks:
        return
    for event in ("post-commit", "post-merge", "post-checkout"):
        hook = tmp_path / ".git" / "hooks" / event
        assert hook.exists()
        content = hook.read_text(encoding="utf-8")
        assert "agentpack:auto-repack" in content
        assert "--agent auto" in content
        assert "GitAutoRepack" in content


def test_init_auto_installs_codex_integration_when_codex_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_CODEX", "1")
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.output
    assert "AGENTS.md" in result.output
    assert (tmp_path / "AGENTS.md").exists()
    assert "agentpack:auto-repack" in (tmp_path / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
