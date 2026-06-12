from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentpack.commands.pack import _mark_session_refreshed
from agentpack.session.state import (
    ACTIVITY_LOG,
    COMPACT_FILE,
    CONTEXT_FILE,
    SESSION_FILE,
    TASK_FILE,
    SessionState,
    create_session,
    load_session,
    log_activity,
    save_session,
    stop_session,
)


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


def test_create_session_creates_files(tmp_root: Path) -> None:
    state = create_session(tmp_root, agent="claude", mode="balanced")

    assert (tmp_root / SESSION_FILE).exists()
    assert (tmp_root / TASK_FILE).exists()
    assert state.active is True
    assert state.agent == "claude"
    assert state.mode == "balanced"
    assert state.started_at is not None


def test_create_session_does_not_overwrite_task(tmp_root: Path) -> None:
    task_path = tmp_root / TASK_FILE
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text("# Custom task\n\nmy existing task\n", encoding="utf-8")

    create_session(tmp_root, agent="generic", mode="balanced")

    assert "my existing task" in task_path.read_text()


def test_load_session_missing_returns_none(tmp_root: Path) -> None:
    assert load_session(tmp_root) is None


def test_load_session_round_trips(tmp_root: Path) -> None:
    state = create_session(tmp_root, agent="codex", mode="deep")
    loaded = load_session(tmp_root)

    assert loaded is not None
    assert loaded.active is True
    assert loaded.agent == "codex"
    assert loaded.mode == "deep"
    assert loaded.started_at == state.started_at


def test_save_and_load_session(tmp_root: Path) -> None:
    state = SessionState(
        active=True,
        started_at="2026-05-04T10:00:00+00:00",
        agent="cursor",
        mode="balanced",
        refresh_count=3,
    )
    save_session(tmp_root, state)
    loaded = load_session(tmp_root)

    assert loaded is not None
    assert loaded.refresh_count == 3
    assert loaded.agent == "cursor"


def test_pack_mark_session_refreshed_updates_active_session(tmp_root: Path) -> None:
    state = create_session(tmp_root, agent="generic", mode="balanced")
    task_path = tmp_root / TASK_FILE
    task_path.write_text("fix refresh state\n", encoding="utf-8")
    result = SimpleNamespace(
        pack=SimpleNamespace(
            freshness={
                "generated_at": "2026-05-13T01:02:03+00:00",
                "snapshot_root_hash": "snap123",
            },
            agent="generic",
            selected_files=[object(), object()],
        ),
        packed_tokens=1234,
    )

    _mark_session_refreshed(tmp_root, result)
    loaded = load_session(tmp_root)

    assert loaded is not None
    assert loaded.last_refresh_at == "2026-05-13T01:02:03+00:00"
    assert loaded.refresh_count == state.refresh_count + 1
    assert loaded.last_task_hash
    assert loaded.last_git_hash == "snap123"
    assert loaded.last_resolved_agent == "generic"


def test_stop_session_marks_inactive(tmp_root: Path) -> None:
    create_session(tmp_root, agent="generic", mode="balanced")
    stop_session(tmp_root)

    state = load_session(tmp_root)
    assert state is not None
    assert state.active is False


def test_stop_session_noop_when_no_session(tmp_root: Path) -> None:
    # Should not raise
    stop_session(tmp_root)


def test_log_activity_appends(tmp_root: Path) -> None:
    create_session(tmp_root, agent="generic", mode="balanced")
    log_activity(tmp_root, "first event")
    log_activity(tmp_root, "second event")

    log_path = tmp_root / ACTIVITY_LOG
    assert log_path.exists()
    content = log_path.read_text()
    assert "first event" in content
    assert "second event" in content
    assert content.count("\n") == 2


def test_session_json_is_valid_json(tmp_root: Path) -> None:
    create_session(tmp_root, agent="claude", mode="deep")
    raw = (tmp_root / SESSION_FILE).read_text()
    data = json.loads(raw)
    assert data["active"] is True
    assert "started_at" in data


def test_session_state_constants() -> None:
    assert SESSION_FILE == ".agentpack/session.json"
    assert TASK_FILE == ".agentpack/task.md"
    assert CONTEXT_FILE == ".agentpack/context.md"
    assert COMPACT_FILE == ".agentpack/context.compact.md"
    assert ACTIVITY_LOG == ".agentpack/activity.log"
