from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import json

AGENTPACK_DIR = ".agentpack"
SESSION_FILE = ".agentpack/session.json"
TASK_FILE = ".agentpack/task.md"
CONTEXT_FILE = ".agentpack/context.md"
COMPACT_FILE = ".agentpack/context.compact.md"
ACTIVITY_LOG = ".agentpack/activity.log"

TASK_FILE_TEMPLATE = """\
# Current Task

Write or update the current coding task here.

AgentPack will refresh context based on this task.
"""


@dataclass
class SessionState:
    active: bool
    started_at: Optional[str]
    agent: str = "generic"
    mode: str = "balanced"
    context_file: str = CONTEXT_FILE
    compact_context_file: str = COMPACT_FILE
    task_file: str = TASK_FILE
    last_refresh_at: Optional[str] = None
    last_task_hash: str = ""
    last_git_hash: str = ""
    refresh_count: int = 0


def load_session(root: Path) -> Optional[SessionState]:
    """Load session state from .agentpack/session.json. Returns None if missing."""
    session_path = root / SESSION_FILE
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
        return SessionState(
            active=data.get("active", False),
            started_at=data.get("started_at"),
            agent=data.get("agent", "generic"),
            mode=data.get("mode", "balanced"),
            context_file=data.get("context_file", CONTEXT_FILE),
            compact_context_file=data.get("compact_context_file", COMPACT_FILE),
            task_file=data.get("task_file", TASK_FILE),
            last_refresh_at=data.get("last_refresh_at"),
            last_task_hash=data.get("last_task_hash", ""),
            last_git_hash=data.get("last_git_hash", ""),
            refresh_count=data.get("refresh_count", 0),
        )
    except FileNotFoundError:
        return None


def save_session(root: Path, state: SessionState) -> None:
    """Write session state to .agentpack/session.json."""
    session_path = root / SESSION_FILE
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(asdict(state), indent=2, default=str),
        encoding="utf-8",
    )


def create_session(root: Path, agent: str, mode: str) -> SessionState:
    """Create a new active session, write session.json, create task.md if missing."""
    (root / AGENTPACK_DIR).mkdir(parents=True, exist_ok=True)

    task_path = root / TASK_FILE
    if not task_path.exists():
        task_path.write_text(TASK_FILE_TEMPLATE, encoding="utf-8")

    state = SessionState(
        active=True,
        started_at=datetime.now(timezone.utc).isoformat(),
        agent=agent,
        mode=mode,
    )
    save_session(root, state)
    return state


def stop_session(root: Path) -> None:
    """Mark the active session as inactive and update session.json."""
    state = load_session(root)
    if state is None:
        return
    state.active = False
    save_session(root, state)


def log_activity(root: Path, message: str) -> None:
    """Append a timestamped line to .agentpack/activity.log."""
    log_path = root / ACTIVITY_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {message}\n")
