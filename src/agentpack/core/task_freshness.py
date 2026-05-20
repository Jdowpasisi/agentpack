from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TASK_FILE = ".agentpack/task.md"
TASK_FILE_DEFAULT_MARKER = "Write or update the current coding task here."


@dataclass(frozen=True)
class TaskFreshness:
    current_task: str | None
    packed_task: str | None
    is_stale: bool
    reason: str = ""


def normalize_task_text(text: str) -> str:
    """Return the first meaningful non-heading task line."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    body = lines[0] if lines else ""
    if TASK_FILE_DEFAULT_MARKER in body:
        return ""
    return " ".join(body.split())


def read_task_md(root: Path) -> str | None:
    path = root / TASK_FILE
    try:
        task = normalize_task_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return task or None


def write_task_md(root: Path, task: str) -> None:
    task_path = root / TASK_FILE
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(task.strip() + "\n", encoding="utf-8")


def task_hash(task: str | None) -> str:
    if not task:
        return ""
    return hashlib.sha256(task.encode("utf-8")).hexdigest()[:16]


def task_metadata(root: Path, packed_task: str) -> dict[str, Any]:
    current_task = read_task_md(root)
    metadata: dict[str, Any] = {
        "packed_task_hash": task_hash(packed_task),
    }
    if current_task:
        metadata["task_md"] = current_task
        metadata["task_md_hash"] = task_hash(current_task)
        metadata["task_matches_task_md"] = current_task == packed_task
    return metadata


def task_freshness(root: Path, metadata: dict[str, Any] | None) -> TaskFreshness:
    current_task = read_task_md(root)
    packed_task = None
    if metadata:
        raw_task = metadata.get("task")
        packed_task = str(raw_task) if raw_task else None
    if current_task and packed_task and current_task != packed_task:
        return TaskFreshness(
            current_task=current_task,
            packed_task=packed_task,
            is_stale=True,
            reason=".agentpack/task.md differs from the packed task",
        )
    return TaskFreshness(
        current_task=current_task,
        packed_task=packed_task,
        is_stale=False,
    )
