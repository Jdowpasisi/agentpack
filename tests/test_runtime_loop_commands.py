from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.models import ContextPack, FileInfo, SelectedFile
from agentpack.core.pack_registry import save_pack_registry
from agentpack.core.scanner import file_hash


runner = CliRunner()


def test_perf_command_reads_session_events(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "session-events.jsonl").write_text(
        json.dumps({"type": "pack", "raw_tokens": 100, "packed_tokens": 25}) + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["perf"])

    assert result.exit_code == 0
    assert "estimated saved tokens" in result.stdout


def test_perf_command_shows_history(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "session-events.jsonl").write_text(
        "\n".join([
            json.dumps({
                "type": "pack",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "raw_tokens": 100,
                "packed_tokens": 25,
            }),
            json.dumps({"type": "retrieve", "timestamp": "2026-01-01T00:01:00+00:00", "path": "src.py"}),
        ]),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["perf", "--history", "2"])

    assert result.exit_code == 0
    assert "Recent Events" in result.stdout
    assert "src.py" in result.stdout


def test_compress_output_command_reads_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / "out.txt").write_text("noise\n" * 50 + "ERROR src/app.py:10 failed\n", encoding="utf-8")

    result = runner.invoke(app, ["compress-output", "out.txt", "--kind", "pytest"])

    assert result.exit_code == 0
    assert "ERROR src/app.py:10 failed" in result.stdout


def test_memory_command_outputs_json(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "session-events.jsonl").write_text(
        json.dumps({
            "type": "learn",
            "task": "fix auth #123",
            "concepts": ["cli"],
            "issue_references": ["#123"],
            "issue_reference_details": [{"ref": "#123", "kind": "github_issue", "title": "Auth bug", "state": "OPEN"}],
        }) + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["memory", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["recent_tasks"] == ["fix auth #123"]
    assert payload["recent_issue_references"] == ["#123"]
    assert payload["issue_reference_details"][0]["title"] == "Auth bug"
    assert payload["top_issue_references"] == [["#123", 1]]


def test_wrap_dry_run_packs_without_launching(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    result = runner.invoke(app, ["wrap", "codex", "--task", "inspect empty repo", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Context ready" in result.output
    assert "AGENTPACK_CONTEXT=" in result.output
    assert "No codex setup file found" in result.output
    assert "Launch command:" in result.output


def test_retrieve_command_reads_pack_registry(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    source = tmp_path / "src.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    pack = ContextPack(
        task="test",
        agent="generic",
        mode="balanced",
        budget=1000,
        token_estimate=10,
        raw_repo_tokens=100,
        after_ignore_tokens=100,
        estimated_savings_percent=90,
        changed_files=["src.py"],
        selected_files=[
            SelectedFile(
                path="src.py",
                score=100,
                include_mode="full",
                reasons=["modified"],
                content="def run():\n    return 1\n",
            )
        ],
        receipts=[],
        freshness={"snapshot_root_hash": "abc", "generated_at": "2026-01-01T00:00:00+00:00"},
    )
    info = FileInfo(
        path="src.py",
        abs_path=source,
        size_bytes=source.stat().st_size,
        estimated_tokens=10,
        hash=file_hash(source),
    )
    save_pack_registry(tmp_path, pack, [info])

    result = runner.invoke(app, ["retrieve", "src.py"])

    assert result.exit_code == 0
    assert "def run()" in result.stdout


def test_learn_feedback_command_records_feedback(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    result = runner.invoke(app, ["learn", "feedback", "helpful", "--target", "card:1"])

    assert result.exit_code == 0
    record = json.loads(
        (tmp_path / ".agentpack" / "learning-feedback.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["feedback"] == "helpful"
    assert record["target"] == "card:1"
