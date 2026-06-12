from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app


def test_benchmark_capture_appends_expected_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentpack.commands.benchmark.git.changed_files_since", lambda _root, _since: {"src/a.py", "tests/test_a.py"})

    result = CliRunner().invoke(app, ["benchmark", "capture", "--since", "main", "--task", "fix a"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".agentpack" / "benchmark.toml").read_text(encoding="utf-8")
    assert 'task = "fix a"' in content
    assert '"src/a.py"' in content
    assert '"tests/test_a.py"' in content


def test_benchmark_capture_writes_anonymous_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr("agentpack.commands.benchmark.git.changed_files_since", lambda _root, _since: {"src/a.py"})

    result = CliRunner().invoke(
        app,
        ["benchmark", "capture", "--since", "main", "--task", "fix a", "--anonymous-report"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".agentpack" / "benchmark-report.md").exists()
    assert (tmp_path / ".agentpack" / "benchmark-report.json").exists()
    assert "No source code uploaded: true" in (tmp_path / ".agentpack" / "benchmark-report.md").read_text(encoding="utf-8")


def test_benchmark_capture_refuses_empty_without_allow_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentpack.commands.benchmark.git.changed_files_since", lambda _root, _since: set())

    result = CliRunner().invoke(app, ["benchmark", "capture", "--since", "main", "--task", "fix a"])

    assert result.exit_code == 1
    assert "No files changed" in result.output


def test_benchmark_from_history_write_cases(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "metrics.jsonl").write_text('{"task": "fix auth", "mode": "minimal"}\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["benchmark", "--from-history", "1", "--write-cases"])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".agentpack" / "benchmark.toml").read_text(encoding="utf-8")
    assert 'task = "fix auth"' in content
    assert 'mode = "balanced"' in content
    assert "expected_files = []" in content
