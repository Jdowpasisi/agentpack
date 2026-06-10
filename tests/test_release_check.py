from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app


def test_release_check_json_orchestrates_stages(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.3] — 2026-05-26\n", encoding="utf-8")

    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return Result()

    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["release-check", "--skip-benchmark", "--skip-build", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert [stage["name"] for stage in payload["stages"]] == [
        "changelog",
        "version-sync",
        "pytest-plugin-deps",
        "ruff",
        "pytest",
        "npm-launcher-tests",
    ]
    assert calls[0] == ["node", "npm/test/version-sync.test.js"]


def test_release_check_fails_missing_changelog_entry(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    result = CliRunner().invoke(app, ["release-check", "--skip-benchmark", "--skip-build"])

    assert result.exit_code == 1
    assert "Missing CHANGELOG.md entry for 1.2.3" in result.output


def test_release_check_build_uses_temp_outdir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## [1.2.3]\n", encoding="utf-8")
    build_commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        parts = [str(part) for part in command]
        if "-m" in parts and "build" in parts:
            build_commands.append(parts)
        return Result()

    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["release-check", "--skip-benchmark", "--json"])

    assert result.exit_code == 0
    assert build_commands
    assert "--outdir" in build_commands[0]
    assert Path(build_commands[0][build_commands[0].index("--outdir") + 1]).name.startswith("agentpack-build-")


def test_release_check_prints_failed_stage_output(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## [1.2.3]\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        if "-m" in [str(part) for part in command] and "pytest" in [str(part) for part in command]:
            return type("Result", (), {"returncode": 1, "stdout": "FAILED tests/test_x.py::test_name\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["release-check", "--skip-benchmark", "--skip-build"])

    assert result.exit_code == 1
    assert "FAILED tests/test_x.py::test_name" in result.output


def test_release_check_fails_pytest_plugin_config_without_dev_dependency(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'version = "1.2.3"',
                "",
                "[project.optional-dependencies]",
                'dev = ["pytest", "ruff"]',
                "",
                "[tool.pytest.ini_options]",
                'asyncio_default_fixture_loop_scope = "function"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text("## [1.2.3]\n", encoding="utf-8")
    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    result = CliRunner().invoke(app, ["release-check", "--skip-benchmark", "--skip-build"])

    assert result.exit_code == 1
    assert "pytest-asyncio options" in result.output


def test_release_check_release_branch_guard_requires_origin_release_branch(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## [1.2.3]\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        if [str(part) for part in command] == ["git", "branch", "-r", "--contains", "HEAD"]:
            return type("Result", (), {"returncode": 0, "stdout": "  origin/main\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["release-check", "--check-release-branch", "--skip-benchmark", "--skip-build"])

    assert result.exit_code == 1
    assert "origin/release/*" in result.output


def test_release_check_registry_guard_fails_existing_versions(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "agentpack-cli"\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## [1.2.3]\n", encoding="utf-8")
    npm_dir = tmp_path / "npm"
    npm_dir.mkdir()
    (npm_dir / "package.json").write_text('{"name": "@example/agentpack", "version": "1.2.3"}', encoding="utf-8")
    monkeypatch.setattr("agentpack.commands.release_check.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr("agentpack.commands.release_check._registry_url_exists", lambda _url: (True, "already published"))

    result = CliRunner().invoke(app, ["release-check", "--check-registry", "--skip-benchmark", "--skip-build", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    failed = {stage["name"]: stage for stage in payload["stages"] if stage["status"] == "failed"}
    assert failed["pypi-version-available"]["detail"] == "already published"
    assert failed["npm-version-available"]["detail"] == "already published"
