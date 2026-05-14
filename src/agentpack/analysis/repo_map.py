from __future__ import annotations

from collections import defaultdict
from typing import Any

from agentpack.core.models import DependencyGraph, FileInfo
from agentpack.core.token_estimator import estimate_tokens


def build_repo_map(
    *,
    files: list[FileInfo],
    scored: list[tuple[FileInfo, float, list[str]]],
    summaries: dict[str, Any],
    dep_graph: DependencyGraph,
    changed_paths: set[str],
    budget_tokens: int = 600,
) -> str:
    """Return a compact semantic map of the repo around the current task."""
    if budget_tokens <= 0 or not files:
        return ""

    file_scores = {fi.path: score for fi, score, _reasons in scored}
    groups: dict[str, list[FileInfo]] = defaultdict(list)
    for fi in files:
        groups[_group_name(fi.path)].append(fi)

    group_rows: list[tuple[float, str, list[FileInfo]]] = []
    for group, members in groups.items():
        score = max((file_scores.get(member.path, 0.0) for member in members), default=0.0)
        if any(member.path in changed_paths for member in members):
            score += 60
        group_rows.append((score, group, members))

    lines = ["Task repo map:"]
    for _score, group, members in sorted(group_rows, reverse=True)[:8]:
        changed_count = sum(1 for member in members if member.path in changed_paths)
        role = _group_role(members, summaries)
        suffix = f"; {changed_count} changed" if changed_count else ""
        candidate = f"- {group}: {len(members)} files; {role}{suffix}"
        if _fits(lines, candidate, budget_tokens):
            lines.append(candidate)

        top_members = sorted(members, key=lambda member: file_scores.get(member.path, 0.0), reverse=True)[:4]
        for member in top_members:
            summary = summaries.get(member.path) or {}
            label = summary.get("role") or _short_summary(summary.get("summary", ""))
            deps = dep_graph.get(member.path)
            rel = ""
            if deps.imports or deps.imported_by:
                rel = f" deps:{len(deps.imports)}/{len(deps.imported_by)}"
            mark = " changed" if member.path in changed_paths else ""
            candidate = f"  - {member.path}: {label or 'source file'}{rel}{mark}"
            if not _fits(lines, candidate, budget_tokens):
                return "\n".join(lines)
            lines.append(candidate)

    return "\n".join(lines) if len(lines) > 1 else ""


def _group_name(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "."
    if parts[0] in {"src", "app", "lib", "tests", "test"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _group_role(members: list[FileInfo], summaries: dict[str, Any]) -> str:
    roles: dict[str, int] = {}
    for member in members:
        summary = summaries.get(member.path) or {}
        role = summary.get("role") or _short_summary(summary.get("summary", ""))
        if role:
            roles[role] = roles.get(role, 0) + 1
    if not roles:
        languages = sorted({member.language or "unknown" for member in members})
        return ", ".join(languages[:3])
    return max(roles.items(), key=lambda item: item[1])[0]


def _short_summary(summary: str) -> str:
    for line in summary.splitlines():
        clean = line.strip("- ").strip()
        if clean.lower().startswith("likely responsibility:"):
            return clean.split(":", 1)[1].strip()
        if clean.lower().startswith("role:"):
            return clean.split(":", 1)[1].strip()
    return ""


def _fits(lines: list[str], candidate: str, budget_tokens: int) -> bool:
    return estimate_tokens("\n".join([*lines, candidate])) <= budget_tokens
