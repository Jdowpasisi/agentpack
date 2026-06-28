from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentpack.core.scanner import file_hash

EPISODIC_CASES_PATH = ".agentpack/episodic-cases.jsonl"


def record_episode(
    root: Path,
    *,
    task: str,
    selected_files: list[str],
    changed_files: list[str],
    checks: list[dict[str, Any]] | None = None,
    passed: bool | None = None,
    failure_class: str = "",
    failure_source: str = "",
    context_hash: str = "",
    output_path: str = EPISODIC_CASES_PATH,
) -> None:
    if not task and not changed_files:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "concepts": sorted(_terms(task)),
        "selected_files": _bounded_paths(selected_files),
        "changed_files": _bounded_paths(changed_files),
        "path_hashes": _path_hashes(root, [*selected_files, *changed_files]),
        "checks": checks or [],
        "passed": passed,
        "failure_class": failure_class,
        "failure_source": failure_source,
        "context_hash": context_hash,
    }
    path = root / output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def episodic_memory_boosts(
    root: Path,
    task: str,
    *,
    output_path: str = EPISODIC_CASES_PATH,
    max_boost: float = 12.0,
    limit: int = 500,
) -> dict[str, float]:
    task_terms = _terms(task)
    if not task_terms:
        return {}
    boosts: dict[str, float] = {}
    for record in _read_jsonl(root / output_path, limit=limit):
        if record.get("passed") is False:
            continue
        episode_terms = _terms(str(record.get("task") or ""))
        for concept in record.get("concepts") or []:
            if isinstance(concept, str):
                episode_terms |= _terms(concept)
        overlap = task_terms & episode_terms
        if not overlap:
            continue
        weight = min(max_boost, 4.0 + len(overlap) * 2.0)
        path_hashes = record.get("path_hashes") if isinstance(record.get("path_hashes"), dict) else {}
        for path in record.get("changed_files") or []:
            if isinstance(path, str) and _path_is_current(root, path, path_hashes):
                boosts[path] = min(max_boost, boosts.get(path, 0.0) + weight)
    return boosts


def _read_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", value.lower())
        if term not in {"the", "and", "for", "with", "this", "that", "from", "into", "agentpack"}
    }


def _bounded_paths(paths: list[str], limit: int = 80) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        value = str(path).strip().replace("\\", "/")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _path_hashes(root: Path, paths: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in _bounded_paths(paths):
        abs_path = root / path
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            hashes[path] = file_hash(abs_path)
        except OSError:
            continue
    return hashes


def _path_is_current(root: Path, path: str, path_hashes: object) -> bool:
    if not path:
        return False
    abs_path = root / path
    if not abs_path.exists() or not abs_path.is_file():
        return False
    if not isinstance(path_hashes, dict):
        return True
    expected = path_hashes.get(path)
    if not isinstance(expected, str) or not expected:
        return True
    try:
        return file_hash(abs_path) == expected
    except OSError:
        return False
