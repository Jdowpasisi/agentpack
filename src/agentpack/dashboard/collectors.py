from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentpack.core import git
from agentpack.core.context_pack import load_pack_metadata
from agentpack.core.loop_protocol import load_loop_state
from agentpack.core.task_freshness import task_freshness
from agentpack.core.thread_context import list_thread_rows
from agentpack.dashboard.models import (
    BenchmarkSummary,
    ContextHealth,
    DashboardSnapshot,
    LearningArtifact,
    LoopSummary,
    ProjectInfo,
    SelectedFileRow,
    SkillFeedbackStatus,
    SkillRow,
    SkillSection,
    SuggestedAction,
    TaskInfo,
    ThreadSummary,
)


MAX_JSONL_ROWS = 500
MAX_RECENT_FEEDBACK = 20
MAX_EXCERPT_CHARS = 1200
MAX_REASONS = 5
MAX_MISSES = 20


def build_project_dashboard_snapshot(root: Path) -> DashboardSnapshot:
    root = root.resolve()
    agentpack_dir = root / ".agentpack"
    meta = load_pack_metadata(root) if agentpack_dir.exists() else None
    task_text = _read_task(agentpack_dir / "task.md") or str((meta or {}).get("task") or "")
    freshness = task_freshness(root, meta) if meta else None
    context = _context_health(meta, freshness)
    selected_files = _selected_files(meta)
    feedback_rows = _load_jsonl(agentpack_dir / "skill_feedback.jsonl")
    skill_section = _skill_section(meta, feedback_rows)
    learning = _learning_artifacts(agentpack_dir)
    benchmarks = _benchmark_summary(
        _load_jsonl(agentpack_dir / "metrics.jsonl"),
        _load_jsonl(agentpack_dir / "benchmark_results.jsonl"),
    )
    threads = _thread_summary(root, meta)
    loop = _loop_summary(root)
    actions = _suggested_actions(agentpack_dir, task_text, context, learning, benchmarks, feedback_rows)

    return DashboardSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        project=_project_info(root, meta),
        task=TaskInfo(
            text=task_text,
            state=_task_state(agentpack_dir / "task_state.md"),
            thread_id=_thread_id(meta),
        ),
        context=context,
        selected_files=selected_files,
        skills=skill_section,
        skill_feedback=_feedback_summary(feedback_rows),
        learning=learning,
        benchmarks=benchmarks,
        threads=threads,
        loop=loop,
        suggested_actions=actions,
    )


def _project_info(root: Path, meta: dict[str, Any] | None) -> ProjectInfo:
    branch = str((meta or {}).get("git_branch") or "")
    sha = str((meta or {}).get("git_sha") or "")
    if git.is_git_repo(root):
        branch = branch or (git.current_branch(root) or "")
        sha = sha or (git.current_sha(root) or "")
    return ProjectInfo(name=root.name, path=str(root), branch=branch, git_sha=sha[:12])


def _thread_id(meta: dict[str, Any] | None) -> str | None:
    concurrent = (meta or {}).get("concurrent_context")
    if isinstance(concurrent, dict):
        thread_id = concurrent.get("thread_id")
        if thread_id:
            return str(thread_id)
    thread_id = (meta or {}).get("thread_id")
    return str(thread_id) if thread_id else None


def _read_task(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _task_state(path: Path) -> str:
    if not path.exists():
        return "unknown"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "unknown"
    valid = {"planned", "in_progress", "blocked", "done"}
    for line in lines:
        if line.lower().startswith("status:"):
            value = line.split(":", 1)[1].strip()
            return value if value in valid else "unknown"
    return "unknown"


def _context_health(meta: dict[str, Any] | None, freshness: Any) -> ContextHealth:
    if not meta:
        return ContextHealth(status="missing")

    status = "fresh"
    stale_reason = ""
    if freshness is not None and getattr(freshness, "is_stale", False):
        status = "stale"
        stale_reason = getattr(freshness, "reason", "") or ""
    elif isinstance(meta.get("freshness"), dict):
        freshness_status = str(meta["freshness"].get("status") or "").lower()
        if freshness_status in {"fresh", "stale", "missing", "unknown"}:
            status = freshness_status
        stale_reason = str(meta["freshness"].get("reason") or meta["freshness"].get("stale_reason") or "")

    selected = meta.get("selected_files_meta") or []
    packed_tokens = _as_int(meta.get("token_estimate"), _as_int(meta.get("packed_tokens"), 0))
    raw_tokens = _as_int(meta.get("raw_tokens"), 0)
    saving_pct = _as_float(meta.get("saving_pct"), 0.0)
    if saving_pct == 0.0 and raw_tokens > 0 and packed_tokens > 0:
        saving_pct = round((1 - packed_tokens / raw_tokens) * 100, 1)

    return ContextHealth(
        status=status,
        generated_at=str(meta.get("generated_at") or ""),
        mode=str(meta.get("mode") or ""),
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        saving_pct=saving_pct,
        selected_files_count=len(selected) if isinstance(selected, list) else 0,
        stale_reason=stale_reason,
    )


def _selected_files(meta: dict[str, Any] | None) -> list[SelectedFileRow]:
    rows: list[SelectedFileRow] = []
    for item in (meta or {}).get("selected_files_meta") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            SelectedFileRow(
                path=str(item.get("path") or ""),
                include_mode=str(item.get("mode") or item.get("include_mode") or ""),
                score=_as_float(item.get("score"), 0.0),
                tokens=_as_int(item.get("tokens"), _as_int(item.get("estimated_tokens"), 0)),
                reasons=_string_list(item.get("reasons"))[:MAX_REASONS],
            )
        )
    return rows


def _skill_section(meta: dict[str, Any] | None, feedback_rows: list[dict[str, Any]]) -> SkillSection:
    feedback = _feedback_summary_by_skill(feedback_rows)
    return SkillSection(
        task_specific=_skill_rows((meta or {}).get("selected_skills") or [], feedback),
        baseline=_skill_rows((meta or {}).get("baseline_skills") or [], feedback),
    )


def _skill_rows(values: list[Any], feedback: dict[str, SkillFeedbackStatus]) -> list[SkillRow]:
    rows: list[SkillRow] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill") if isinstance(item.get("skill"), dict) else item
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name") or item.get("name") or "")
        if not name:
            continue
        rows.append(
            SkillRow(
                name=name,
                path=str(skill.get("path") or ""),
                confidence=_as_float(item.get("confidence"), 0.0),
                score=_as_float(item.get("score"), 0.0),
                side_effect_level=str(skill.get("side_effect_level") or ""),
                status=feedback.get(name.lower(), "none"),
                reasons=_string_list(item.get("reasons"))[:MAX_REASONS],
            )
        )
    return rows


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-MAX_JSONL_ROWS:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _feedback_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "recent": rows[-MAX_RECENT_FEEDBACK:],
        "summary_by_skill": _feedback_summary_by_skill(rows),
    }


def _feedback_summary_by_skill(rows: list[dict[str, Any]]) -> dict[str, SkillFeedbackStatus]:
    status: dict[str, SkillFeedbackStatus] = {}
    precedence = {
        "none": 0,
        "recommended_only": 1,
        "ignored": 2,
        "used_helpful": 3,
        "used_noisy": 4,
        "bad_recommendation": 5,
    }

    def assign(skill: Any, new_status: SkillFeedbackStatus) -> None:
        key = str(skill).strip().lower()
        if not key:
            return
        current = status.get(key, "none")
        if precedence[new_status] >= precedence[current]:
            status[key] = new_status

    for row in rows:
        for skill in _string_list(row.get("recommended_skills")):
            assign(skill, "recommended_only")
        for skill in _string_list(row.get("used_skills")):
            feedback = str(row.get("user_feedback") or "").lower()
            assign(skill, "used_noisy" if feedback in {"bad", "noisy", "unhelpful", "not-helpful"} else "used_helpful")
        for skill in _string_list(row.get("ignored_skills")):
            assign(skill, "ignored")
        for skill in _string_list(row.get("bad_recommendations")):
            assign(skill, "bad_recommendation")
    return status


def _learning_artifacts(agentpack_dir: Path) -> list[LearningArtifact]:
    artifacts = [
        ("Learning notes", "learning.md"),
        ("Daily summary", "daily-summary.md"),
        ("Agent lessons", "agent-lessons.md"),
        ("Skill progress", "skills-progress.json"),
        ("Learning feedback", "learning-feedback.jsonl"),
    ]
    return [
        LearningArtifact(
            label=label,
            path=f".agentpack/{name}",
            exists=(agentpack_dir / name).exists(),
            excerpt=_bounded_excerpt(agentpack_dir / name),
        )
        for label, name in artifacts
    ]


def _bounded_excerpt(path: Path, limit: int = MAX_EXCERPT_CHARS) -> str:
    if not path.exists() or path.suffix == ".jsonl":
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit]


def _benchmark_summary(metrics_rows: list[dict[str, Any]], benchmark_rows: list[dict[str, Any]]) -> BenchmarkSummary:
    numeric_keys = [
        "selection_recall",
        "selection_precision",
        "selection_token_precision",
        "rank_at_k",
        "skill_recall_at_3",
        "skill_precision_at_3",
        "skill_mrr",
        "skill_noise_rate",
    ]
    recent = metrics_rows[-10:] + benchmark_rows[-10:]
    averages: dict[str, float] = {}
    for key in numeric_keys:
        values = [_as_float(row[key], 0.0) for row in recent if _is_number(row.get(key))]
        if values:
            averages[key] = sum(values) / len(values)
    latest = (benchmark_rows or metrics_rows or [{}])[-1]
    misses = [miss for row in benchmark_rows[-5:] for miss in (row.get("misses") or row.get("missed_expected") or []) if isinstance(miss, dict)]
    return BenchmarkSummary(latest=latest, averages=averages, misses=misses[:MAX_MISSES])


def _thread_summary(root: Path, meta: dict[str, Any] | None) -> ThreadSummary:
    rows = list_thread_rows(root, active_only=True)
    conflicts: list[dict[str, Any]] = []
    concurrent = (meta or {}).get("concurrent_context")
    if isinstance(concurrent, dict):
        raw_conflicts = concurrent.get("conflicts") or []
        if isinstance(raw_conflicts, list):
            conflicts = [item for item in raw_conflicts if isinstance(item, dict)]
    return ThreadSummary(active_count=len(rows), conflicts=conflicts)


def _loop_summary(root: Path) -> LoopSummary:
    state = load_loop_state(root)
    if state is None:
        return LoopSummary()
    return LoopSummary(
        exists=True,
        status=state.status,
        task=state.task,
        iteration=state.iteration,
        max_iterations=state.max_iterations,
        runner=state.runner,
        last_runner_status=_result_status(state.last_runner),
        last_verification_status=_result_status(state.last_verification),
        blocked_reason=state.blocked_reason,
        next_action=_loop_next_action(state.status, state.task, state.runner, bool(state.verification_commands)),
    )


def _suggested_actions(
    agentpack_dir: Path,
    task_text: str,
    context: ContextHealth,
    learning: list[LearningArtifact],
    benchmarks: BenchmarkSummary,
    feedback_rows: list[dict[str, Any]],
) -> list[SuggestedAction]:
    actions: list[SuggestedAction] = []
    if not agentpack_dir.exists():
        actions.append(
            SuggestedAction(
                label="Initialize AgentPack",
                command="agentpack init --yes",
                reason="No .agentpack directory exists.",
            )
        )
    if not task_text:
        actions.append(
            SuggestedAction(
                label="Start a task",
                command='agentpack work "describe the task"',
                reason="No current task found.",
            )
        )
    if context.status in {"missing", "stale"}:
        actions.append(
            SuggestedAction(
                label="Refresh context",
                command="agentpack pack --task auto",
                reason=f"Context is {context.status}.",
            )
        )
    if not any(item.exists for item in learning):
        actions.append(
            SuggestedAction(
                label="Generate learning notes",
                command="agentpack learn",
                reason="No learning artifacts found.",
            )
        )
    if not benchmarks.averages:
        actions.append(
            SuggestedAction(
                label="Initialize benchmarks",
                command="agentpack benchmark --init",
                reason="No benchmark metrics found.",
            )
        )
    if not feedback_rows:
        actions.append(
            SuggestedAction(
                label="Record skill feedback",
                command='agentpack skills feedback --task "..." --recommended-skill skill-name --user-feedback helpful',
                reason="No skill feedback found.",
            )
        )
    return actions


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _result_status(result: Any) -> str:
    if result is None:
        return ""
    return "passed" if getattr(result, "returncode", 1) == 0 else "failed"


def _loop_next_action(status: str, task: str, runner: str, has_verification: bool) -> str:
    if not runner:
        return 'agentpack work "..." --run --runner "..."'
    if not has_verification:
        return f'agentpack work "{task}" --run --verify "pytest -q"'
    if status == "ready_to_finish":
        return "agentpack finish --since main"
    if status == "blocked":
        return "agentpack dashboard"
    return f'agentpack work "{task}" --run'
