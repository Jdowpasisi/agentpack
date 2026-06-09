from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentpack.core import git
from agentpack.session.state import TASK_FILE


@dataclass
class LearningInputs:
    task: str
    since: str | None
    changed_files: dict[str, str]
    diffs: dict[str, str] = field(default_factory=dict)
    redaction_warnings: list[str] = field(default_factory=list)


def collect_learning_inputs(
    root: Path,
    *,
    since: str | None,
    max_changed_files: int,
    max_diff_chars_per_file: int,
) -> LearningInputs:
    task = _read_task(root)
    changed = git.diff_name_status(root, since=since)
    limited_paths = list(changed)[:max_changed_files]
    diffs: dict[str, str] = {}
    warnings: list[str] = []
    for path in limited_paths:
        diff, redaction_warnings = git.file_diff(
            root,
            path,
            since=since,
            max_chars=max_diff_chars_per_file,
        )
        diffs[path] = diff
        warnings.extend(redaction_warnings)
    return LearningInputs(
        task=task,
        since=since,
        changed_files={path: changed[path] for path in limited_paths},
        diffs=diffs,
        redaction_warnings=warnings,
    )


def _read_task(root: Path) -> str:
    path = root / TASK_FILE
    if not path.exists():
        return git.infer_task_from_git(root) if git.is_git_repo(root) else "Current work"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return lines[0] if lines else "Current work"
