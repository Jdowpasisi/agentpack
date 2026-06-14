from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from agentpack.cli import app


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    (root / ".agentpack").mkdir()
    (root / ".agentpack" / "task.md").write_text("Migrate stale AgentPack repo\n", encoding="utf-8")
    (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return root


def test_migrate_repairs_exact_repo_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    repo = _repo(tmp_path / "repo")
    (repo / "AGENTS.md").write_text(
        "<!-- agentpack:start -->\n"
        "Old AgentPack instructions: run agentpack pack --task auto and read context.md\n"
        "<!-- agentpack:end -->\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["migrate", "--path", str(repo), "--agent", "codex"])

    assert result.exit_code == 0, result.output
    assert "repaired" in result.output
    assert "agentpack guard --agent codex --repair-stale --refresh-context" in (
        repo / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert list((tmp_path / "codex-home" / "plugins" / "cache" / "local" / "agentpack").glob("*/.codex-plugin/plugin.json"))


def test_migrate_discover_repairs_nested_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    repo = _repo(tmp_path / "workspace" / "nested")
    (repo / "AGENTS.md").write_text(
        "<!-- agentpack:start -->\n"
        "Old AgentPack instructions: run agentpack pack --task auto and read context.md\n"
        "<!-- agentpack:end -->\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["migrate", "--path", str(tmp_path / "workspace"), "--discover", "--agent", "codex"],
    )

    assert result.exit_code == 0, result.output
    assert "Migrating 1 repo(s)" in result.output
    assert "agentpack guard --agent codex --repair-stale --refresh-context" in (
        repo / "AGENTS.md"
    ).read_text(encoding="utf-8")


def test_migrate_dry_run_does_not_write(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    repo = _repo(tmp_path / "repo")
    old_content = (
        "<!-- agentpack:start -->\n"
        "Old AgentPack instructions: run agentpack pack --task auto and read context.md\n"
        "<!-- agentpack:end -->\n"
    )
    (repo / "AGENTS.md").write_text(old_content, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["migrate", "--path", str(repo), "--agent", "codex", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Would repair codex integration" in result.output
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == old_content
    assert not (tmp_path / "codex-home").exists()


def test_migrate_refreshes_context(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    repo = _repo(tmp_path / "repo")

    result = CliRunner().invoke(
        app,
        ["migrate", "--path", str(repo), "--agent", "generic", "--refresh-context"],
    )

    assert result.exit_code == 0, result.output
    assert "context refreshed" in result.output
    assert (repo / ".agentpack" / "context.md").exists()
