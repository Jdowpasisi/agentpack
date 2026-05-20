from __future__ import annotations

from pathlib import Path

from agentpack.core.task_freshness import (
    normalize_task_text,
    read_task_md,
    task_freshness,
    task_hash,
    task_metadata,
    write_task_md,
)


def test_normalize_task_text_uses_first_non_heading_line() -> None:
    assert normalize_task_text("# Task\n\nfix auth token\nmore detail") == "fix auth token"


def test_read_task_md_ignores_placeholder(tmp_path: Path) -> None:
    task_path = tmp_path / ".agentpack" / "task.md"
    task_path.parent.mkdir()
    task_path.write_text("Write or update the current coding task here.\n", encoding="utf-8")

    assert read_task_md(tmp_path) is None


def test_task_metadata_records_hashes(tmp_path: Path) -> None:
    write_task_md(tmp_path, "fix auth token")

    metadata = task_metadata(tmp_path, "fix auth token")

    assert metadata["task_md"] == "fix auth token"
    assert metadata["task_matches_task_md"] is True
    assert metadata["packed_task_hash"] == task_hash("fix auth token")
    assert metadata["task_md_hash"] == task_hash("fix auth token")


def test_task_freshness_detects_task_md_mismatch(tmp_path: Path) -> None:
    write_task_md(tmp_path, "fix current task")

    state = task_freshness(tmp_path, {"task": "fix old task"})

    assert state.is_stale is True
    assert state.current_task == "fix current task"
    assert state.packed_task == "fix old task"
    assert ".agentpack/task.md differs" in state.reason
