from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.commands.init import _patch_repo_gitignore, _repo_gitignore_block


def test_repo_gitignore_block_ignores_generated_artifacts() -> None:
    block = _repo_gitignore_block()

    assert ".agentpack/cache/" in block
    assert ".agentpack/context*" in block
    assert ".agentpack/.gitignore" in block
    assert ".agentpack/.mcp_reminded" in block
    assert ".agentpack/session.json" in block
    assert ".agentpack/task.md" in block
    assert ".agent/skills/agentpack/" in block
    assert ".agentpack/config.toml" not in block


def test_repo_gitignore_block_respects_share_cache() -> None:
    block = _repo_gitignore_block(share_cache=True)

    assert ".agentpack/cache/" not in block
    assert ".agentpack/snapshots/" in block


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

    assert ".agentpack/cache/" not in content
    assert content.count("# agentpack:start") == 1


def test_init_writes_repo_gitignore_block(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".agentpack/context*" in content
    assert ".agentpack/config.toml" not in content
    assert ".agentpack/task.md" in content


@pytest.mark.parametrize(
    ("agent", "expected_files", "expected_git_hooks"),
    [
        ("claude", ("CLAUDE.md", ".claude/settings.json", ".mcp.json"), False),
        ("cursor", (".cursorrules", ".cursor/rules/agentpack.mdc", ".vscode/tasks.json"), True),
        ("windsurf", (".windsurfrules", ".vscode/tasks.json"), True),
        ("codex", ("AGENTS.md",), True),
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
