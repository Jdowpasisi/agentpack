from __future__ import annotations

import json
from pathlib import Path

_TASK_LABEL = "AgentPack: Repack context"
_TASK_LABEL_AUTO = "AgentPack: Repack (auto task)"


def _agentpack_tasks(agent: str) -> list[dict]:
    return [
        {
            "label": _TASK_LABEL,
            "type": "shell",
            "command": f"agentpack pack --agent {agent} --task auto --mode balanced",
            "group": "none",
            "presentation": {"reveal": "always", "panel": "shared"},
            "problemMatcher": [],
        },
        {
            "label": _TASK_LABEL_AUTO,
            "type": "shell",
            "command": f"agentpack pack --agent {agent} --task auto --mode balanced",
            "runOptions": {"runOn": "folderOpen"},
            "group": "none",
            "presentation": {"reveal": "silent", "panel": "shared"},
            "problemMatcher": [],
        },
    ]


def install_vscode_tasks(root: Path, agent: str) -> str:
    """Merge agentpack tasks into .vscode/tasks.json. Returns action taken.

    Idempotent — safe to re-run. Existing tasks with matching labels are
    updated; other tasks are preserved.
    """
    vscode_dir = root / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    tasks_path = vscode_dir / "tasks.json"

    existing: dict = {"version": "2.0.0", "tasks": []}
    if tasks_path.exists():
        try:
            existing = json.loads(tasks_path.read_text())
        except json.JSONDecodeError:
            pass

    existing.setdefault("version", "2.0.0")
    existing.setdefault("tasks", [])

    new_tasks = _agentpack_tasks(agent)
    new_labels = {t["label"] for t in new_tasks}

    # Remove stale agentpack tasks, keep everything else
    kept = [t for t in existing["tasks"] if t.get("label") not in new_labels]
    had_any = len(kept) < len(existing["tasks"])

    existing["tasks"] = kept + new_tasks
    tasks_path.write_text(json.dumps(existing, indent=2) + "\n")

    return "updated" if had_any else "created"


def remove_vscode_tasks(root: Path) -> str:
    """Remove agentpack tasks from .vscode/tasks.json. Returns action taken."""
    tasks_path = root / ".vscode" / "tasks.json"
    if not tasks_path.exists():
        return "unchanged"

    try:
        existing = json.loads(tasks_path.read_text())
    except json.JSONDecodeError:
        return "unchanged"

    labels = {_TASK_LABEL, _TASK_LABEL_AUTO}
    before = len(existing.get("tasks", []))
    existing["tasks"] = [t for t in existing.get("tasks", []) if t.get("label") not in labels]
    after = len(existing["tasks"])

    if before == after:
        return "unchanged"

    tasks_path.write_text(json.dumps(existing, indent=2) + "\n")
    return "cleaned"
