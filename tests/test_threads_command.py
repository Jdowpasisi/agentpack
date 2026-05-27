from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.thread_context import append_thread_index, build_thread_index_row


def test_threads_json_lists_latest_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    row = build_thread_index_row(
        root=tmp_path,
        thread_id="thread-a",
        task="fix auth",
        branch="main",
        selected_files=["src/auth.py"],
        dirty_files=[],
        status="in_progress",
    )
    append_thread_index(tmp_path, row)

    result = CliRunner().invoke(app, ["threads", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["thread_id"] == "thread-a"
    assert payload[0]["task"] == "fix auth"


def test_threads_active_filters_done_and_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    active = build_thread_index_row(root=tmp_path, thread_id="active", task="a", branch="main", selected_files=[], dirty_files=[], status="in_progress")
    done = build_thread_index_row(root=tmp_path, thread_id="done", task="d", branch="main", selected_files=[], dirty_files=[], status="done")
    stale = build_thread_index_row(root=tmp_path, thread_id="stale", task="s", branch="main", selected_files=[], dirty_files=[], status="in_progress")
    stale["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    for row in (active, done, stale):
        append_thread_index(tmp_path, row)

    result = CliRunner().invoke(app, ["threads", "--active", "--json"])

    assert result.exit_code == 0
    ids = {row["thread_id"] for row in json.loads(result.output)}
    assert ids == {"active"}


def test_threads_conflicts_filters_to_overlaps(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    append_thread_index(tmp_path, build_thread_index_row(root=tmp_path, thread_id="a", task="a", branch="main", selected_files=["src/auth.py"], dirty_files=[], status="in_progress"))
    append_thread_index(tmp_path, build_thread_index_row(root=tmp_path, thread_id="b", task="b", branch="main", selected_files=["src/auth.py"], dirty_files=[], status="in_progress"))
    append_thread_index(tmp_path, build_thread_index_row(root=tmp_path, thread_id="c", task="c", branch="other", selected_files=["src/auth.py"], dirty_files=[], status="in_progress"))

    result = CliRunner().invoke(app, ["threads", "--conflicts", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert {row["thread_id"] for row in rows} == {"a", "b"}
    assert rows[0]["conflict_count"] == 1


def test_threads_archive_marks_done_and_writes_state(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    append_thread_index(tmp_path, build_thread_index_row(root=tmp_path, thread_id="a", task="a", branch="main", selected_files=[], dirty_files=[], status="in_progress"))

    result = CliRunner().invoke(app, ["threads", "archive", "a", "--summary", "Complete"])

    assert result.exit_code == 0
    assert "Status: done" in (tmp_path / ".agentpack" / "threads" / "a" / "task_state.md").read_text()
    latest = json.loads((tmp_path / ".agentpack" / "thread_index.jsonl").read_text().splitlines()[-1])
    assert latest["status"] == "done"


def test_threads_prune_dry_run_and_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    old = build_thread_index_row(root=tmp_path, thread_id="old", task="old", branch="main", selected_files=[], dirty_files=[], status="done")
    old["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    append_thread_index(tmp_path, old)
    thread_dir = tmp_path / ".agentpack" / "threads" / "old"
    thread_dir.mkdir(parents=True)

    dry = CliRunner().invoke(app, ["threads", "prune", "--older-than", "7d"])
    assert dry.exit_code == 0
    assert thread_dir.exists()

    delete = CliRunner().invoke(app, ["threads", "prune", "--older-than", "7d", "--yes"])
    assert delete.exit_code == 0
    assert not thread_dir.exists()
