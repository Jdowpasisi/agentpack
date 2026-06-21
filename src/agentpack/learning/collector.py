from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentpack.core import git
from agentpack.core.context_pack import load_pack_metadata
from agentpack.session.references import collect_repo_issue_references
from agentpack.session.state import TASK_FILE


@dataclass
class LearningInputs:
    task: str
    changed_files: dict[str, str]
    since: str | None = None
    since_date: str | None = None
    diffs: dict[str, str] = field(default_factory=dict)
    redaction_warnings: list[str] = field(default_factory=list)
    selected_files: list[str] = field(default_factory=list)
    selected_modes: dict[str, str] = field(default_factory=dict)
    issue_references: list[str] = field(default_factory=list)
    issue_reference_details: list[dict] = field(default_factory=list)


def collect_learning_inputs(
    root: Path,
    *,
    since: str | None,
    since_date: str | None = None,
    max_changed_files: int,
    max_diff_chars_per_file: int,
) -> LearningInputs:
    task = _read_task(root)
    changed = git.diff_name_status_since_date(root, since_date) if since_date else git.diff_name_status(root, since=since)
    limited_paths = list(changed)[:max_changed_files]
    diffs: dict[str, str] = {}
    warnings: list[str] = []
    for path in limited_paths:
        if since_date:
            diff, redaction_warnings = git.file_diff_since_date(root, path, since_date, max_chars=max_diff_chars_per_file)
        else:
            diff, redaction_warnings = git.file_diff(
                root,
                path,
                since=since,
                max_chars=max_diff_chars_per_file,
            )
        diffs[path] = diff
        warnings.extend(redaction_warnings)
    selected_files, selected_modes = _latest_selected_files(root)
    issue_reference_details = collect_repo_issue_references(root, task)
    return LearningInputs(
        task=task,
        since=since,
        since_date=since_date,
        changed_files={path: changed[path] for path in limited_paths},
        diffs=diffs,
        redaction_warnings=warnings,
        selected_files=selected_files,
        selected_modes=selected_modes,
        issue_references=[item.ref for item in issue_reference_details],
        issue_reference_details=[item.to_dict() for item in issue_reference_details],
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


def _latest_selected_files(root: Path) -> tuple[list[str], dict[str, str]]:
    metadata = load_pack_metadata(root) or {}
    raw = metadata.get("selected_files_meta") or metadata.get("selected_files") or []
    selected: list[str] = []
    modes: dict[str, str] = {}
    if not isinstance(raw, list):
        return selected, modes
    for item in raw:
        if isinstance(item, str):
            selected.append(item)
            continue
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if isinstance(path, str):
            selected.append(path)
            mode = item.get("mode")
            if isinstance(mode, str):
                modes[path] = mode
    return selected, modes
