from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agentpack.session.state import (
    TASK_FILE, CONTEXT_FILE, COMPACT_FILE, SESSION_FILE,
    create_session, load_session,
)
from agentpack.commands.session import _run_refresh


# ---------------------------------------------------------------------------
# _run_refresh with mocked PackService
# ---------------------------------------------------------------------------

def _make_mock_result(files: int = 5, tokens: int = 8000, saving: float = 85.0):
    pack = MagicMock()
    pack.selected_files = [MagicMock() for _ in range(files)]
    pack.task = "fix bug"
    pack.mode = "balanced"
    pack.budget = 25000
    pack.token_estimate = tokens
    pack.raw_repo_tokens = 80000
    pack.after_ignore_tokens = 70000
    pack.estimated_savings_percent = saving
    pack.changed_files = []
    pack.receipts = []
    pack.redaction_warnings = []
    pack.stale = False

    result = MagicMock()
    result.pack = pack
    result.packed_tokens = tokens
    result.saving_pct = saving
    return result


def test_run_refresh_writes_context_files(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / TASK_FILE).write_text("# Task\n\nfix login bug\n", encoding="utf-8")

    mock_result = _make_mock_result(files=5, tokens=8000)

    with patch("agentpack.application.pack_service.PackService") as MockPS, \
         patch("agentpack.renderers.markdown.render_generic", return_value="# Context\n\ncontent"), \
         patch("agentpack.renderers.compact.render_compact", return_value="# Compact\n\ncontent"):
        MockPS.return_value.run.return_value = mock_result
        result = _run_refresh(tmp_path, agent="generic", mode="balanced", budget=0)

    assert result is not None
    assert result["files"] == 5
    assert result["tokens"] == 8000
    assert (tmp_path / CONTEXT_FILE).exists()
    assert (tmp_path / COMPACT_FILE).exists()


def test_run_refresh_reads_task_from_task_md(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    task_path = tmp_path / TASK_FILE
    task_path.write_text("# Task\n\nfix auth token expiry\n", encoding="utf-8")

    captured_requests: list = []

    def capture_run(request):
        captured_requests.append(request)
        return _make_mock_result()

    with patch("agentpack.application.pack_service.PackService") as MockPS, \
         patch("agentpack.renderers.markdown.render_generic", return_value=""), \
         patch("agentpack.renderers.compact.render_compact", return_value=""):
        MockPS.return_value.run.side_effect = capture_run
        _run_refresh(tmp_path, agent="generic", mode="balanced", budget=0)

    assert len(captured_requests) == 1
    assert "fix auth token expiry" in captured_requests[0].task


def test_run_refresh_fallback_when_no_task_md(tmp_path: Path, monkeypatch) -> None:
    """No task.md → falls back without crashing."""
    (tmp_path / ".agentpack").mkdir()

    with patch("agentpack.application.pack_service.PackService") as MockPS, \
         patch("agentpack.core.git.is_git_repo", return_value=False), \
         patch("agentpack.renderers.markdown.render_generic", return_value=""), \
         patch("agentpack.renderers.compact.render_compact", return_value=""):
        MockPS.return_value.run.return_value = _make_mock_result()
        result = _run_refresh(tmp_path, agent="generic", mode="balanced", budget=0)

    assert result is not None


def test_run_refresh_uses_git_infer_when_no_task(tmp_path: Path) -> None:
    """Empty task.md → infers task from git."""
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / TASK_FILE).write_text("# Task\n\n", encoding="utf-8")

    captured: list = []

    def capture_run(request):
        captured.append(request.task)
        return _make_mock_result()

    with patch("agentpack.application.pack_service.PackService") as MockPS, \
         patch("agentpack.core.git.is_git_repo", return_value=True), \
         patch("agentpack.core.git.infer_task_from_git", return_value="inferred: fix bug"), \
         patch("agentpack.renderers.markdown.render_generic", return_value=""), \
         patch("agentpack.renderers.compact.render_compact", return_value=""):
        MockPS.return_value.run.side_effect = capture_run
        _run_refresh(tmp_path, agent="generic", mode="balanced", budget=0)

    assert len(captured) == 1
    assert captured[0] == "inferred: fix bug"


def test_run_refresh_returns_none_on_error(tmp_path: Path) -> None:
    with patch("agentpack.application.pack_service.PackService") as MockPS:
        MockPS.return_value.run.side_effect = RuntimeError("pack failed")
        result = _run_refresh(tmp_path, agent="generic", mode="balanced", budget=0)
    assert result is None


# ---------------------------------------------------------------------------
# Context refresh when git diff changes (integration-style via session state)
# ---------------------------------------------------------------------------

def test_session_refresh_updates_last_task_hash(tmp_path: Path) -> None:
    create_session(tmp_path, agent="generic", mode="balanced")
    task_path = tmp_path / TASK_FILE
    task_path.write_text("# Task\n\nnew task\n", encoding="utf-8")

    with patch("agentpack.commands.session._run_refresh") as mock_refresh:
        mock_refresh.return_value = {"files": 3, "tokens": 5000, "saving": 80.0}
        from typer.testing import CliRunner
        from agentpack.cli import app
        runner = CliRunner()
        import os; os.chdir(tmp_path)
        result = runner.invoke(app, ["session", "refresh"])

    assert result.exit_code == 0
    state = load_session(tmp_path)
    assert state is not None
    expected_hash = hashlib.sha256(task_path.read_bytes()).hexdigest()[:16]
    assert state.last_task_hash == expected_hash
