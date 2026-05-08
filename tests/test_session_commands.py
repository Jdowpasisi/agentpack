from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.session.state import (
    SESSION_FILE, TASK_FILE, load_session, create_session,
)

runner = CliRunner()


@pytest.fixture()
def tmp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# session start
# ---------------------------------------------------------------------------

def test_session_start_creates_session_json(tmp_repo: Path) -> None:
    result = runner.invoke(app, ["session", "start", "--agent", "generic", "--mode", "minimal"])
    assert (tmp_repo / SESSION_FILE).exists(), result.output
    state = load_session(tmp_repo)
    assert state is not None
    assert state.active is True
    assert state.agent == "generic"
    assert state.mode == "minimal"


def test_session_start_creates_task_md(tmp_repo: Path) -> None:
    runner.invoke(app, ["session", "start"])
    assert (tmp_repo / TASK_FILE).exists()


def test_session_start_does_not_overwrite_existing_task(tmp_repo: Path) -> None:
    (tmp_repo / ".agentpack").mkdir(parents=True, exist_ok=True)
    task_path = tmp_repo / TASK_FILE
    task_path.write_text("# Custom task\n\nexisting content\n", encoding="utf-8")
    runner.invoke(app, ["session", "start"])
    assert "existing content" in task_path.read_text()


def test_session_start_with_task_flag_writes_task(tmp_repo: Path) -> None:
    runner.invoke(app, ["session", "start", "--task", "fix login bug"])
    content = (tmp_repo / TASK_FILE).read_text()
    assert "fix login bug" in content


# ---------------------------------------------------------------------------
# session stop
# ---------------------------------------------------------------------------

def test_session_stop_marks_inactive(tmp_repo: Path) -> None:
    create_session(tmp_repo, agent="generic", mode="balanced")
    result = runner.invoke(app, ["session", "stop"])
    assert result.exit_code == 0
    state = load_session(tmp_repo)
    assert state is not None
    assert state.active is False


def test_session_stop_no_session_exits_nonzero(tmp_repo: Path) -> None:
    result = runner.invoke(app, ["session", "stop"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# session status
# ---------------------------------------------------------------------------

def test_session_status_shows_active(tmp_repo: Path) -> None:
    create_session(tmp_repo, agent="cursor", mode="deep")
    result = runner.invoke(app, ["session", "status"])
    assert result.exit_code == 0
    assert "cursor" in result.output
    assert "deep" in result.output


def test_session_status_no_session_exits_nonzero(tmp_repo: Path) -> None:
    result = runner.invoke(app, ["session", "status"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# session refresh
# ---------------------------------------------------------------------------

_FAKE_RESULT = {"files": 7, "tokens": 12000, "saving": 88.5}


def test_session_refresh_updates_session_state(tmp_repo: Path) -> None:
    create_session(tmp_repo, agent="generic", mode="balanced")
    with patch("agentpack.commands.session._run_refresh", return_value=_FAKE_RESULT):
        result = runner.invoke(app, ["session", "refresh"])
    assert result.exit_code == 0
    state = load_session(tmp_repo)
    assert state is not None
    assert state.refresh_count == 1
    assert state.last_refresh_at is not None


def test_session_refresh_no_session_exits_nonzero(tmp_repo: Path) -> None:
    result = runner.invoke(app, ["session", "refresh"])
    assert result.exit_code != 0


def test_session_refresh_task_override_writes_task(tmp_repo: Path) -> None:
    create_session(tmp_repo, agent="generic", mode="balanced")
    with patch("agentpack.commands.session._run_refresh", return_value=_FAKE_RESULT):
        runner.invoke(app, ["session", "refresh", "--task", "fix the bug"])
    content = (tmp_repo / TASK_FILE).read_text()
    assert "fix the bug" in content
