from __future__ import annotations

import hashlib
import fnmatch
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from agentpack.core import git
from agentpack.core.config import LoopConfig


LOOP_STATE_FILE = ".agentpack/loop_state.json"
PROGRESS_FILE = ".agentpack/progress.md"
LOOP_EVENTS_FILE = ".agentpack/loop_events.jsonl"
LOOP_FAILURES_FILE = ".agentpack/loop_failures.jsonl"
LOOP_DIAGNOSIS_FILE = ".agentpack/loop_diagnosis.md"
LOOP_ACCEPTANCE_FILE = ".agentpack/loop_acceptance.md"
LOOP_HANDOFF_FILE = ".agentpack/loop_handoff.md"
LOOP_RISK_FILE = ".agentpack/loop_risk_review.md"
LOOP_REVIEW_FILE = ".agentpack/loop_reviewer_summary.md"
LOOP_METRICS_FILE = ".agentpack/loop_metrics.jsonl"
LOOP_ROLLBACK_DIR = ".agentpack/loop_rollback"
LOOP_RUNNER_PROMPT_FILE = ".agentpack/loop_runner_prompt.md"
MAX_EXCERPT_CHARS = 4000

LoopStatus = Literal["idle", "running", "blocked", "ready_to_finish", "done"]
RunnerStatus = Literal["changed", "blocked", "no_change", "unknown"]


class LoopCommandResult(BaseModel):
    command: str
    returncode: int
    output_excerpt: str = ""
    duration_s: float = 0.0
    timed_out: bool = False


class LoopPhaseRecord(BaseModel):
    phase: str
    status: str
    iteration: int
    detail: str = ""
    timestamp: str = ""


class LoopDiffSnapshot(BaseModel):
    hash: str = ""
    files_changed: list[str] = Field(default_factory=list)
    stat: str = ""
    changed: bool = False


class LoopRunnerContract(BaseModel):
    status: RunnerStatus = "unknown"
    summary: str = ""
    files_changed: list[str] = Field(default_factory=list)
    blocker: str = ""
    acceptance: dict[str, str] = Field(default_factory=dict)


class LoopRiskReview(BaseModel):
    level: str = "low"
    reasons: list[str] = Field(default_factory=list)
    changed_files_count: int = 0
    rollback_patch: str = ""


class LoopState(BaseModel):
    schema_version: int = 1
    enabled: bool = True
    task: str
    status: LoopStatus = "idle"
    iteration: int = 0
    max_iterations: int = 10
    runner: str = ""
    runner_adapter: str = ""
    runner_prompt_output: str = LOOP_RUNNER_PROMPT_FILE
    verification_commands: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    risk_sensitive_globs: list[str] = Field(default_factory=list)
    risk_high_file_count: int = 20
    runner_timeout_seconds: int = 600
    verification_timeout_seconds: int = 600
    max_repeated_failures: int = 3
    repeated_failure_count: int = 0
    last_failure_fingerprint: str = ""
    last_runner: LoopCommandResult | None = None
    last_runner_contract: LoopRunnerContract | None = None
    last_verification: LoopCommandResult | None = None
    last_diff: LoopDiffSnapshot = Field(default_factory=LoopDiffSnapshot)
    risk_review: LoopRiskReview = Field(default_factory=LoopRiskReview)
    failure_class: str = ""
    acceptance_file: str = ""
    handoff_file: str = ""
    risk_review_file: str = ""
    reviewer_file: str = ""
    runner_prompt_file: str = ""
    rollback_patch: str = ""
    previous_diff_hash: str = ""
    no_change_iterations: int = 0
    phase_history: list[LoopPhaseRecord] = Field(default_factory=list)
    progress_updates: int = 0
    started_at: str = ""
    updated_at: str = ""
    blocked_reason: str = ""
    finish_summary: str = ""


class LoopPlan(BaseModel):
    task: str
    runner: str
    verification_commands: list[str]
    max_iterations: int
    status: LoopStatus
    next_action: str


class LoopRunSummary(BaseModel):
    status: LoopStatus
    iterations: int
    reason: str = ""
    next_command: str = ""


class FinishBlocker(BaseModel):
    kind: str
    message: str
    command: str


def load_loop_state(root: Path) -> LoopState | None:
    path = root / LOOP_STATE_FILE
    if not path.exists():
        return None
    try:
        return LoopState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_loop_state(root: Path, state: LoopState) -> None:
    state.updated_at = _now()
    path = root / LOOP_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def initialize_loop(
    root: Path,
    task: str,
    cfg: LoopConfig,
    *,
    runner_override: str = "",
    max_iterations_override: int = 0,
    verification_overrides: list[str] | None = None,
    acceptance_overrides: list[str] | None = None,
) -> LoopState:
    now = _now()
    state = LoopState(
        enabled=cfg.enabled,
        task=task.strip(),
        status="idle",
        max_iterations=max_iterations_override or cfg.max_iterations,
        runner=(runner_override or cfg.runner).strip(),
        runner_adapter=cfg.runner_adapter.strip(),
        runner_prompt_output=cfg.runner_prompt_output,
        verification_commands=[item.strip() for item in (verification_overrides if verification_overrides is not None else cfg.verification_commands) if item.strip()],
        acceptance_checks=[item.strip() for item in (acceptance_overrides if acceptance_overrides is not None else cfg.acceptance_checks) if item.strip()],
        risk_sensitive_globs=[item.strip() for item in cfg.risk_sensitive_globs if item.strip()],
        risk_high_file_count=cfg.risk_high_file_count,
        runner_timeout_seconds=cfg.runner_timeout_seconds,
        verification_timeout_seconds=cfg.verification_timeout_seconds,
        max_repeated_failures=cfg.max_repeated_failures,
        started_at=now,
        updated_at=now,
    )
    baseline = _capture_diff_snapshot(root, "")
    baseline.changed = False
    state.last_diff = baseline
    state.previous_diff_hash = baseline.hash
    state.runner_prompt_file = _write_runner_prompt(root, state)
    save_loop_state(root, state)
    _write_progress(root, state, "initialized", "Loop initialized.")
    _append_event(root, "initialized", state, {"task": state.task})
    return state


def dry_run_plan(root: Path, state: LoopState) -> LoopPlan:
    if not state.runner and state.runner_adapter:
        state.runner = resolve_runner_adapter(state.runner_adapter, root)
    save_loop_state(root, state)
    return LoopPlan(
        task=state.task,
        runner=state.runner,
        verification_commands=state.verification_commands,
        max_iterations=state.max_iterations,
        status=state.status,
        next_action=_next_action(state),
    )


def run_loop(
    root: Path,
    state: LoopState,
    *,
    refresh: Callable[[], LoopCommandResult],
    run_command: Callable[[str, int], LoopCommandResult] | None = None,
) -> LoopRunSummary:
    if not state.runner:
        if state.runner_adapter:
            state.runner = resolve_runner_adapter(state.runner_adapter, root)
            save_loop_state(root, state)
    if not state.runner:
        return _block(root, state, "missing_runner", 'Set [loop].runner or pass --runner to `agentpack work "..." --run`.')
    if not state.verification_commands:
        return _block(root, state, "missing_verification", "Set [loop].verification_commands or pass --verify.")

    execute = run_command or (lambda command, timeout: _run_shell(command, timeout, cwd=root))
    state.status = "running"
    _record_phase(state, "prepare_context", "ready", "loop started")
    save_loop_state(root, state)

    while state.iteration < state.max_iterations:
        state.iteration += 1
        _append_event(root, "iteration_started", state, {"iteration": state.iteration})
        _record_phase(state, "prepare_context", "running", "refreshing context")
        refresh_result = refresh()
        _append_event(root, "context_refresh", state, refresh_result.model_dump(mode="json"))
        if refresh_result.returncode != 0:
            _record_phase(state, "prepare_context", "failed", refresh_result.output_excerpt)
            return _block(root, state, "context_refresh_failed", refresh_result.output_excerpt)

        _record_phase(state, "run_agent", "running", state.runner)
        state.rollback_patch = _write_rollback_patch(root, state)
        runner_result = execute(state.runner, state.runner_timeout_seconds)
        state.last_runner = runner_result
        contract = _parse_runner_contract(runner_result)
        state.last_runner_contract = contract
        _append_event(root, "runner_result", state, runner_result.model_dump(mode="json"))
        _append_event(root, "runner_contract", state, contract.model_dump(mode="json"))
        if runner_result.returncode != 0:
            _record_phase(state, "run_agent", "failed", runner_result.output_excerpt)
            _append_failure(root, state, "runner_failed", runner_result)
            return _block(root, state, "runner_failed", runner_result.output_excerpt)
        if contract.status == "blocked":
            detail = contract.blocker or contract.summary or runner_result.output_excerpt
            _record_phase(state, "run_agent", "blocked", detail)
            _write_loop_diagnosis(root, state, "runner_blocked", detail)
            return _block(root, state, "runner_blocked", detail)

        _record_phase(state, "collect_diff", "running", "capturing git diff")
        diff_snapshot = _capture_diff_snapshot(root, state.previous_diff_hash)
        state.last_diff = diff_snapshot
        state.risk_review = _review_loop_risk(state)
        state.risk_review_file = _write_risk_review(root, state)
        state.previous_diff_hash = diff_snapshot.hash
        state.no_change_iterations = 0 if diff_snapshot.changed else state.no_change_iterations + 1
        _append_event(root, "diff_snapshot", state, diff_snapshot.model_dump(mode="json"))
        _record_phase(
            state,
            "collect_diff",
            "changed" if diff_snapshot.changed else "no_change",
            ", ".join(diff_snapshot.files_changed[:8]) or "no git diff",
        )
        if contract.status == "no_change" or (state.iteration > 1 and bool(diff_snapshot.hash) and not diff_snapshot.changed):
            _write_loop_diagnosis(root, state, "no_diff_change", "Runner completed but git diff did not change.")
            return _block(root, state, "no_diff_change", "Runner completed but git diff did not change.")

        _record_phase(state, "run_verification", "running", "running verification commands")
        verification_result = _run_verifications(state, execute)
        state.last_verification = verification_result
        _append_event(root, "verification_result", state, verification_result.model_dump(mode="json"))
        if verification_result.returncode == 0:
            _record_phase(state, "run_verification", "passed", verification_result.output_excerpt)
            _record_phase(state, "finish_gate", "ready", "verification passed")
            state.status = "ready_to_finish"
            state.blocked_reason = ""
            state.acceptance_file = _write_acceptance(root, state)
            state.reviewer_file = _write_reviewer_summary(root, state)
            save_loop_state(root, state)
            _write_progress(root, state, "ready_to_finish", "Verification passed. Run agentpack finish.")
            _write_loop_diagnosis(root, state, "ready_to_finish", "Verification passed.")
            _append_loop_metric(root, state, "ready_to_finish")
            return LoopRunSummary(status="ready_to_finish", iterations=state.iteration, next_command="agentpack finish --since main")

        _record_phase(state, "run_verification", "failed", verification_result.output_excerpt)
        _append_failure(root, state, "verification_failed", verification_result)
        state.failure_class = _classify_failure(verification_result)
        fingerprint = _failure_fingerprint(verification_result)
        state.repeated_failure_count = state.repeated_failure_count + 1 if fingerprint == state.last_failure_fingerprint else 1
        state.last_failure_fingerprint = fingerprint
        save_loop_state(root, state)
        _write_progress(root, state, "verification_failed", verification_result.output_excerpt)
        _record_phase(state, "diagnose_failure", "written", verification_result.output_excerpt)
        _write_loop_diagnosis(root, state, "verification_failed", verification_result.output_excerpt)
        if state.repeated_failure_count >= state.max_repeated_failures:
            _record_phase(state, "decide_continue_or_block", "blocked", "same verification failure repeated")
            return _block(root, state, "repeated_verification_failure", verification_result.output_excerpt)
        _record_phase(state, "decide_continue_or_block", "continue", f"attempt {state.iteration + 1}")

    return _block(root, state, "max_iterations_reached", f"Reached {state.max_iterations} iterations.")


def finish_blockers(
    root: Path,
    cfg: LoopConfig,
    state: LoopState | None,
    *,
    allow_empty_diff: bool = False,
    allow_high_risk: bool = False,
) -> list[FinishBlocker]:
    if not cfg.enabled or state is None:
        return []
    blockers: list[FinishBlocker] = []
    if state.status not in {"ready_to_finish", "done"}:
        blockers.append(
            FinishBlocker(
                kind="loop_not_ready",
                message=f"Ralph Loop is {state.status}; finish requires ready_to_finish.",
                command=f'agentpack work "{state.task}" --run',
            )
        )
    if cfg.require_verification and (state.last_verification is None or state.last_verification.returncode != 0):
        blockers.append(
            FinishBlocker(
                kind="verification_missing",
                message="No passing loop verification is recorded.",
                command=f'agentpack work "{state.task}" --run --verify "pytest -q"',
            )
        )
    if cfg.require_progress_update and not _progress_exists(root):
        blockers.append(
            FinishBlocker(
                kind="progress_missing",
                message="No loop progress update is recorded.",
                command=f'agentpack work "{state.task}" --run --dry-run',
            )
        )
    if not allow_empty_diff and not state.last_diff.changed:
        blockers.append(
            FinishBlocker(
                kind="empty_loop_diff",
                message="Ralph Loop has no recorded post-run source diff; use --allow-empty-capture if this task intentionally changed nothing.",
                command="git status --short",
            )
        )
    if not state.acceptance_file:
        blockers.append(
            FinishBlocker(
                kind="acceptance_missing",
                message="No loop acceptance summary is recorded.",
                command="cat .agentpack/loop_acceptance.md",
            )
        )
    missing_acceptance = _missing_acceptance_checks(state)
    if missing_acceptance:
        blockers.append(
            FinishBlocker(
                kind="acceptance_checks_missing",
                message=f"Loop acceptance checks are not passed: {', '.join(missing_acceptance[:5])}",
                command=f"cat {state.acceptance_file or LOOP_ACCEPTANCE_FILE}",
            )
        )
    if not allow_high_risk and state.risk_review.level == "high":
        blockers.append(
            FinishBlocker(
                kind="high_risk_diff",
                message="Loop risk review is high; inspect before finishing.",
                command="cat .agentpack/loop_risk_review.md",
            )
        )
    if state.repeated_failure_count >= state.max_repeated_failures and state.status != "done":
        blockers.append(
            FinishBlocker(
                kind="repeated_failure_unresolved",
                message="Ralph Loop stopped on repeated verification failure before a clean pass.",
                command="cat .agentpack/loop_diagnosis.md",
            )
        )
    if cfg.require_clean_tree:
        dirty = sorted(git.dirty_files(root))
        if dirty:
            blockers.append(
                FinishBlocker(
                    kind="dirty_worktree",
                    message=f"Worktree has uncommitted changes: {', '.join(dirty[:5])}",
                    command="git status --short",
                )
            )
    return blockers


def mark_done(root: Path, summary: str) -> None:
    state = load_loop_state(root)
    if state is None:
        return
    state.status = "done"
    state.finish_summary = summary
    save_loop_state(root, state)
    _write_progress(root, state, "done", summary)
    _append_loop_metric(root, state, "done")
    _append_event(root, "done", state, {"summary": summary})


def _run_verifications(state: LoopState, execute: Callable[[str, int], LoopCommandResult]) -> LoopCommandResult:
    outputs: list[str] = []
    started = time.perf_counter()
    for command in state.verification_commands:
        result = execute(command, state.verification_timeout_seconds)
        outputs.append(f"$ {command}\n{result.output_excerpt}")
        if result.returncode != 0:
            result.output_excerpt = _excerpt("\n\n".join(outputs))
            result.duration_s = round(time.perf_counter() - started, 3)
            return result
    return LoopCommandResult(
        command=" && ".join(state.verification_commands),
        returncode=0,
        output_excerpt=_excerpt("\n\n".join(outputs)),
        duration_s=round(time.perf_counter() - started, 3),
    )


def _run_shell(command: str, timeout_seconds: int, *, cwd: Path | None = None) -> LoopCommandResult:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output = ((result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")).strip()
        return LoopCommandResult(
            command=command,
            returncode=result.returncode,
            output_excerpt=_excerpt(output),
            duration_s=round(time.perf_counter() - started, 3),
        )
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + ("\n" if exc.stdout and exc.stderr else "") + (exc.stderr or "")).strip()
        return LoopCommandResult(
            command=command,
            returncode=124,
            output_excerpt=_excerpt(output or f"Command timed out after {timeout_seconds}s."),
            duration_s=round(time.perf_counter() - started, 3),
            timed_out=True,
        )


def _block(root: Path, state: LoopState, reason: str, detail: str) -> LoopRunSummary:
    state.status = "blocked"
    state.blocked_reason = reason
    _record_phase(state, "decide_continue_or_block", "blocked", f"{reason}: {detail}")
    save_loop_state(root, state)
    _write_progress(root, state, "blocked", f"{reason}: {detail}")
    _write_loop_diagnosis(root, state, reason, detail)
    state.handoff_file = _write_handoff(root, state, reason, detail)
    save_loop_state(root, state)
    _append_loop_metric(root, state, "blocked", reason=reason)
    _append_event(root, "blocked", state, {"reason": reason, "detail": _excerpt(detail)})
    return LoopRunSummary(status="blocked", iterations=state.iteration, reason=reason, next_command=_next_action(state))


def _write_progress(root: Path, state: LoopState, title: str, body: str) -> None:
    path = root / PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# AgentPack Ralph Loop Progress\n\n"
    entry = f"## {_now()} - {title}\n\nTask: {state.task}\n\n{_excerpt(body)}\n\n"
    path.write_text(existing.rstrip() + "\n\n" + entry, encoding="utf-8")
    state.progress_updates += 1
    save_loop_state(root, state)


def _append_event(root: Path, event: str, state: LoopState, payload: dict) -> None:
    _append_jsonl(root / LOOP_EVENTS_FILE, {"ts": _now(), "event": event, "task": state.task, "iteration": state.iteration, **payload})


def _append_failure(root: Path, state: LoopState, kind: str, result: LoopCommandResult) -> None:
    _append_jsonl(root / LOOP_FAILURES_FILE, {"ts": _now(), "kind": kind, "task": state.task, "iteration": state.iteration, **result.model_dump(mode="json")})


def _record_phase(state: LoopState, phase: str, status: str, detail: str = "") -> None:
    state.phase_history.append(
        LoopPhaseRecord(
            phase=phase,
            status=status,
            iteration=state.iteration,
            detail=_excerpt(detail),
            timestamp=_now(),
        )
    )
    state.phase_history = state.phase_history[-50:]


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _progress_exists(root: Path) -> bool:
    path = root / PROGRESS_FILE
    return path.exists() and bool(path.read_text(encoding="utf-8").strip())


def _failure_fingerprint(result: LoopCommandResult) -> str:
    raw = f"{result.command}\0{result.returncode}\0{result.output_excerpt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def resolve_runner_adapter(adapter: str, root: Path) -> str:
    name = adapter.strip().lower()
    if not name or name == "generic":
        return ""
    prompt = LOOP_RUNNER_PROMPT_FILE
    if name == "claude":
        if not shutil.which("claude"):
            return ""
        return f'claude --print --permission-mode acceptEdits "$(cat {prompt})"'
    if name == "codex":
        if not shutil.which("codex"):
            return ""
        return f'codex exec --ignore-user-config --sandbox workspace-write "$(cat {prompt})"'
    if name == "cursor":
        if shutil.which("cursor-agent"):
            return f'cursor-agent --print --force "$(cat {prompt})"'
        return ""
    return ""


def _parse_runner_contract(result: LoopCommandResult) -> LoopRunnerContract:
    text = result.output_excerpt.strip()
    for raw in reversed(text.splitlines() or [text]):
        line = raw.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = data.get("status")
        if status not in {"changed", "blocked", "no_change"}:
            status = "unknown"
        files = data.get("files_changed") or []
        if not isinstance(files, list):
            files = []
        acceptance = data.get("acceptance") or {}
        if isinstance(acceptance, list):
            acceptance = {
                str(item.get("check") or ""): str(item.get("status") or "")
                for item in acceptance
                if isinstance(item, dict) and item.get("check")
            }
        if not isinstance(acceptance, dict):
            acceptance = {}
        return LoopRunnerContract(
            status=status,
            summary=str(data.get("summary") or "")[:1000],
            files_changed=[str(item) for item in files[:50]],
            blocker=str(data.get("blocker") or "")[:1000],
            acceptance={str(k): str(v) for k, v in acceptance.items()},
        )
    return LoopRunnerContract(status="unknown", summary=_excerpt(text))


def _capture_diff_snapshot(root: Path, previous_hash: str) -> LoopDiffSnapshot:
    status_out = git._run(["git", "status", "--porcelain=v1"], root) or ""
    diff_stat = git._run(["git", "diff", "--stat"], root) or ""
    cached_stat = git._run(["git", "diff", "--cached", "--stat"], root) or ""
    files = sorted(git.dirty_files(root))
    file_hashes: list[str] = []
    for rel in files[:200]:
        path = root / rel
        if path.is_file():
            try:
                file_hashes.append(f"{rel}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
            except OSError:
                file_hashes.append(f"{rel}:unreadable")
        else:
            file_hashes.append(f"{rel}:missing")
    raw = status_out + "\n" + diff_stat + "\n" + cached_stat + "\n" + "\n".join(file_hashes)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw.strip() else ""
    return LoopDiffSnapshot(
        hash=digest,
        files_changed=files,
        stat=_excerpt((diff_stat + "\n" + cached_stat).strip()),
        changed=bool(digest and digest != previous_hash),
    )


def _write_rollback_patch(root: Path, state: LoopState) -> str:
    out = git._run(["git", "diff", "--binary"], root) or ""
    cached = git._run(["git", "diff", "--cached", "--binary"], root) or ""
    text = (out + "\n" + cached).strip()
    if not text:
        return ""
    path = root / LOOP_ROLLBACK_DIR / f"iteration-{state.iteration}-before.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return _rel(path, root)


def _review_loop_risk(state: LoopState) -> LoopRiskReview:
    reasons: list[str] = []
    files = state.last_diff.files_changed
    high_terms = ("migration", "migrations/", "auth", "security", "permission", "billing", "payment", "schema")
    if any(any(term in path.lower() for term in high_terms) for path in files):
        reasons.append("sensitive path changed")
    if state.risk_sensitive_globs and any(
        any(fnmatch.fnmatch(path, pattern) for pattern in state.risk_sensitive_globs)
        for path in files
    ):
        reasons.append("configured sensitive path changed")
    if any(path.endswith((".lock", "package.json", "pyproject.toml", "go.mod", "pom.xml")) for path in files):
        reasons.append("dependency or package metadata changed")
    if len(files) > state.risk_high_file_count:
        reasons.append("broad diff touches more than 20 files")
    if any("D " in line or line.startswith(" delete") for line in state.last_diff.stat.splitlines()):
        reasons.append("deleted files present")
    level = "high" if any(reason in reasons for reason in ("sensitive path changed", "configured sensitive path changed", "broad diff touches more than 20 files")) else ("medium" if reasons else "low")
    return LoopRiskReview(level=level, reasons=reasons, changed_files_count=len(files), rollback_patch=state.rollback_patch)


def _write_risk_review(root: Path, state: LoopState) -> str:
    path = root / LOOP_RISK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    risk = state.risk_review
    lines = [
        "# AgentPack Ralph Loop Risk Review",
        "",
        f"- Level: {risk.level}",
        f"- Changed files: {risk.changed_files_count}",
        f"- Rollback patch: {risk.rollback_patch or '(none)'}",
        f"- Reasons: {', '.join(risk.reasons) or 'none'}",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- {path}" for path in state.last_diff.files_changed[:100])
    (root / LOOP_RISK_FILE).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return LOOP_RISK_FILE


def _write_acceptance(root: Path, state: LoopState) -> str:
    path = root / LOOP_ACCEPTANCE_FILE
    contract = state.last_runner_contract or LoopRunnerContract()
    acceptance = contract.acceptance or {}
    lines = [
        "# AgentPack Ralph Loop Acceptance",
        "",
        f"- Task: {state.task}",
        f"- Verification: passed ({state.last_verification.command if state.last_verification else 'none'})",
        f"- Runner status: {contract.status}",
        f"- Runner summary: {contract.summary or '(none)'}",
        f"- Changed files: {', '.join(state.last_diff.files_changed[:50]) or '(none)'}",
        f"- Risk level: {state.risk_review.level}",
        "",
        "## Acceptance Checks",
        "",
    ]
    if state.acceptance_checks:
        for check in state.acceptance_checks:
            lines.append(f"- {check}: {acceptance.get(check, 'missing')}")
    else:
        lines.append("- No semantic acceptance checks configured.")
    lines += [
        "",
        "Reviewer still owns semantic correctness; this file records loop evidence, not final approval.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return LOOP_ACCEPTANCE_FILE


def _write_reviewer_summary(root: Path, state: LoopState) -> str:
    path = root / LOOP_REVIEW_FILE
    lines = [
        "# AgentPack Ralph Loop Reviewer Summary",
        "",
        f"- Task: {state.task}",
        f"- Status: {state.status}",
        f"- Iterations: {state.iteration}/{state.max_iterations}",
        f"- Verification: {state.last_verification.command if state.last_verification else '(none)'}",
        f"- Risk: {state.risk_review.level}",
        f"- Changed files: {', '.join(state.last_diff.files_changed[:50]) or '(none)'}",
        f"- Rollback patch: {state.rollback_patch or '(none)'}",
        f"- Acceptance: {state.acceptance_file or '(none)'}",
        f"- Diagnosis: {LOOP_DIAGNOSIS_FILE}",
        "",
        "## Review Notes",
        "",
        "Check the risk review and changed files before merging. Passing verification is evidence, not reviewer approval.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return LOOP_REVIEW_FILE


def _classify_failure(result: LoopCommandResult) -> str:
    text = result.output_excerpt.lower()
    if "assert" in text or "expected" in text or "actual" in text:
        return "test_assertion"
    if "importerror" in text or "modulenotfounderror" in text or "cannot find module" in text:
        return "import_error"
    if "typeerror" in text or "mypy" in text or "tsc" in text:
        return "type_error"
    if "timeout" in text or result.timed_out:
        return "timeout"
    if "permission denied" in text or "unauthorized" in text or "forbidden" in text:
        return "permission_or_auth"
    if "connection refused" in text or "network" in text:
        return "environment_or_network"
    return "unknown"


def _write_handoff(root: Path, state: LoopState, reason: str, detail: str) -> str:
    path = root / LOOP_HANDOFF_FILE
    contract = state.last_runner_contract or LoopRunnerContract()
    lines = [
        "# AgentPack Ralph Loop Handoff",
        "",
        f"- Task: {state.task}",
        f"- Status: {state.status}",
        f"- Reason: {reason}",
        f"- Failure class: {state.failure_class or 'unknown'}",
        f"- Iteration: {state.iteration}/{state.max_iterations}",
        f"- Runner summary: {contract.summary or '(none)'}",
        f"- Changed files: {', '.join(state.last_diff.files_changed[:50]) or '(none)'}",
        f"- Rollback patch: {state.rollback_patch or '(none)'}",
        f"- Diagnosis: {LOOP_DIAGNOSIS_FILE}",
        f"- Risk review: {state.risk_review_file or LOOP_RISK_FILE}",
        "",
        "## Last Detail",
        "",
        _excerpt(detail) or "(none)",
        "",
        "## Suggested Next Step",
        "",
        "Inspect diagnosis, review diff risk, then rerun the loop or apply rollback patch if edits are not salvageable.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return LOOP_HANDOFF_FILE


def _write_runner_prompt(root: Path, state: LoopState) -> str:
    path = root / state.runner_prompt_output
    path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_lines = "\n".join(f"- {item}" for item in state.acceptance_checks) or "- No configured semantic checks."
    verify_lines = "\n".join(f"- `{item}`" for item in state.verification_commands) or "- No configured verification."
    body = f"""# AgentPack Ralph Loop Runner Contract

Task:
{state.task}

Context:
- Read `.agentpack/context.md` or the agent-specific context file before editing.
- Keep edits focused on the task.
- Do not commit, push, delete unrelated files, or run destructive commands.

Verification commands AgentPack will run:
{verify_lines}

Acceptance checks:
{acceptance_lines}

On the final output line, print one JSON object:

```json
{{"status":"changed","summary":"what changed","files_changed":["path"],"blocker":"","acceptance":{{"check":"pass"}}}}
```

Use `status=blocked` with `blocker` when you cannot proceed. Use
`status=no_change` when no edit is required.
"""
    path.write_text(body, encoding="utf-8")
    return _rel(path, root)


def _missing_acceptance_checks(state: LoopState) -> list[str]:
    if not state.acceptance_checks:
        return []
    contract = state.last_runner_contract or LoopRunnerContract()
    passed = {key for key, value in contract.acceptance.items() if str(value).lower() in {"pass", "passed", "true", "ok"}}
    return [check for check in state.acceptance_checks if check not in passed]


def _append_loop_metric(root: Path, state: LoopState, outcome: str, *, reason: str = "") -> None:
    _append_jsonl(
        root / LOOP_METRICS_FILE,
        {
            "ts": _now(),
            "task": state.task,
            "outcome": outcome,
            "reason": reason,
            "iterations": state.iteration,
            "status": state.status,
            "risk_level": state.risk_review.level,
            "failure_class": state.failure_class,
            "changed_files_count": len(state.last_diff.files_changed),
        },
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _write_loop_diagnosis(root: Path, state: LoopState, reason: str, detail: str) -> None:
    path = root / LOOP_DIAGNOSIS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    contract = state.last_runner_contract or LoopRunnerContract()
    verification = state.last_verification or LoopCommandResult(command="", returncode=0)
    lines = [
        "# AgentPack Ralph Loop Diagnosis",
        "",
        f"- Task: {state.task}",
        f"- Status: {state.status}",
        f"- Iteration: {state.iteration}/{state.max_iterations}",
        f"- Reason: {reason}",
        f"- Repeated failures: {state.repeated_failure_count}/{state.max_repeated_failures}",
        f"- Diff hash: {state.last_diff.hash or '(none)'}",
        f"- Changed files: {', '.join(state.last_diff.files_changed[:20]) or '(none)'}",
        f"- Runner status: {contract.status}",
        f"- Runner summary: {contract.summary or '(none)'}",
        f"- Runner blocker: {contract.blocker or '(none)'}",
        f"- Verification command: {verification.command or '(none)'}",
        f"- Verification returncode: {verification.returncode}",
        "",
        "## Detail",
        "",
        _excerpt(detail) or "(none)",
        "",
        "## Diff Stat",
        "",
        state.last_diff.stat or "(none)",
        "",
        "## Recent Phases",
        "",
    ]
    for item in state.phase_history[-12:]:
        lines.append(f"- {item.timestamp} iter={item.iteration} {item.phase}: {item.status} - {item.detail}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _next_action(state: LoopState) -> str:
    if not state.runner:
        return "configure [loop].runner or pass --runner"
    if not state.verification_commands:
        return "configure [loop].verification_commands or pass --verify"
    if state.status == "ready_to_finish":
        return "agentpack finish --since main"
    if state.status == "blocked":
        return "inspect .agentpack/loop_failures.jsonl"
    return f'agentpack work "{state.task}" --run'


def _excerpt(value: str) -> str:
    text = str(value or "")
    return text[-MAX_EXCERPT_CHARS:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
