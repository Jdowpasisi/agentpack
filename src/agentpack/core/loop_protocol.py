from __future__ import annotations

import hashlib
import json
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
MAX_EXCERPT_CHARS = 4000

LoopStatus = Literal["idle", "running", "blocked", "ready_to_finish", "done"]


class LoopCommandResult(BaseModel):
    command: str
    returncode: int
    output_excerpt: str = ""
    duration_s: float = 0.0
    timed_out: bool = False


class LoopState(BaseModel):
    schema_version: int = 1
    enabled: bool = True
    task: str
    status: LoopStatus = "idle"
    iteration: int = 0
    max_iterations: int = 10
    runner: str = ""
    verification_commands: list[str] = Field(default_factory=list)
    runner_timeout_seconds: int = 600
    verification_timeout_seconds: int = 600
    max_repeated_failures: int = 3
    repeated_failure_count: int = 0
    last_failure_fingerprint: str = ""
    last_runner: LoopCommandResult | None = None
    last_verification: LoopCommandResult | None = None
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
) -> LoopState:
    now = _now()
    state = LoopState(
        enabled=cfg.enabled,
        task=task.strip(),
        status="idle",
        max_iterations=max_iterations_override or cfg.max_iterations,
        runner=(runner_override or cfg.runner).strip(),
        verification_commands=[item.strip() for item in (verification_overrides if verification_overrides is not None else cfg.verification_commands) if item.strip()],
        runner_timeout_seconds=cfg.runner_timeout_seconds,
        verification_timeout_seconds=cfg.verification_timeout_seconds,
        max_repeated_failures=cfg.max_repeated_failures,
        started_at=now,
        updated_at=now,
    )
    save_loop_state(root, state)
    _write_progress(root, state, "initialized", "Loop initialized.")
    _append_event(root, "initialized", state, {"task": state.task})
    return state


def dry_run_plan(root: Path, state: LoopState) -> LoopPlan:
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
        return _block(root, state, "missing_runner", 'Set [loop].runner or pass --runner to `agentpack work "..." --run`.')
    if not state.verification_commands:
        return _block(root, state, "missing_verification", "Set [loop].verification_commands or pass --verify.")

    execute = run_command or _run_shell
    state.status = "running"
    save_loop_state(root, state)

    while state.iteration < state.max_iterations:
        state.iteration += 1
        _append_event(root, "iteration_started", state, {"iteration": state.iteration})
        refresh_result = refresh()
        _append_event(root, "context_refresh", state, refresh_result.model_dump(mode="json"))
        if refresh_result.returncode != 0:
            return _block(root, state, "context_refresh_failed", refresh_result.output_excerpt)

        runner_result = execute(state.runner, state.runner_timeout_seconds)
        state.last_runner = runner_result
        _append_event(root, "runner_result", state, runner_result.model_dump(mode="json"))
        if runner_result.returncode != 0:
            _append_failure(root, state, "runner_failed", runner_result)
            return _block(root, state, "runner_failed", runner_result.output_excerpt)

        verification_result = _run_verifications(state, execute)
        state.last_verification = verification_result
        _append_event(root, "verification_result", state, verification_result.model_dump(mode="json"))
        if verification_result.returncode == 0:
            state.status = "ready_to_finish"
            state.blocked_reason = ""
            save_loop_state(root, state)
            _write_progress(root, state, "ready_to_finish", "Verification passed. Run agentpack finish.")
            return LoopRunSummary(status="ready_to_finish", iterations=state.iteration, next_command="agentpack finish --since main")

        _append_failure(root, state, "verification_failed", verification_result)
        fingerprint = _failure_fingerprint(verification_result)
        state.repeated_failure_count = state.repeated_failure_count + 1 if fingerprint == state.last_failure_fingerprint else 1
        state.last_failure_fingerprint = fingerprint
        save_loop_state(root, state)
        _write_progress(root, state, "verification_failed", verification_result.output_excerpt)
        if state.repeated_failure_count >= state.max_repeated_failures:
            return _block(root, state, "repeated_verification_failure", verification_result.output_excerpt)

    return _block(root, state, "max_iterations_reached", f"Reached {state.max_iterations} iterations.")


def finish_blockers(root: Path, cfg: LoopConfig, state: LoopState | None) -> list[FinishBlocker]:
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


def _run_shell(command: str, timeout_seconds: int) -> LoopCommandResult:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            shell=True,
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
    save_loop_state(root, state)
    _write_progress(root, state, "blocked", f"{reason}: {detail}")
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
