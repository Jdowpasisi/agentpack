from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.ignore import agentignore_sync_status


def test_agentignore_sync_reads_nested_gitignores_and_exclude_sources(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("**/dist/\n", encoding="utf-8")
    (tmp_path / "apps" / "web" / ".gitignore").write_text("dist/\n**/cache/\ngenerated\\ output/\n", encoding="utf-8")
    (tmp_path / ".git" / "info" / "exclude").write_text("build\\cache\\\n", encoding="utf-8")

    fake_home = tmp_path / "home"
    (fake_home / ".config" / "git").mkdir(parents=True)
    (fake_home / ".config" / "git" / "ignore").write_text("reports/\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)

    status = agentignore_sync_status(tmp_path)

    assert "**/dist/" in status.imported_rules
    assert "apps/web/dist/" in status.imported_rules
    assert "apps/web/**/cache/" in status.imported_rules
    assert "apps/web/generated output/" in status.imported_rules
    assert "build/cache/" in status.imported_rules
    assert "reports/" in status.imported_rules
    assert any(source.path == ".gitignore" for source in status.imported_sources)
    assert any(source.path == "apps/web/.gitignore" for source in status.imported_sources)
    assert any(source.path == ".git/info/exclude" for source in status.imported_sources)
    assert any(source.path == "~/.config/git/ignore" for source in status.imported_sources)


def test_agentignore_sync_keeps_generated_subpaths_under_src(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("src/generated/\n", encoding="utf-8")

    status = agentignore_sync_status(tmp_path)

    assert "src/generated/" in status.imported_rules


def test_ignore_sync_command_updates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["ignore", "sync"])

    assert result.exit_code == 0, result.output
    assert "Created .agentignore." in result.output
    assert "backend/.serverless/" in (tmp_path / ".agentignore").read_text(encoding="utf-8")


def test_ignore_sync_check_detects_stale_import_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")
    (tmp_path / ".agentignore").write_text("custom/\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["ignore", "sync", "--check"])

    assert result.exit_code == 1
    assert ".agentignore is stale" in result.output
