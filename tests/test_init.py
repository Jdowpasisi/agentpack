from __future__ import annotations

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
