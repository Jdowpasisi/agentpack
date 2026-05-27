from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root
from agentpack.core import git
from agentpack.core.thread_context import (
    append_thread_index,
    build_thread_index_row,
    detect_conflicts,
    list_thread_rows,
    sanitize_thread_id,
    thread_paths,
)

threads_app = typer.Typer(help="Inspect and clean up AgentPack thread-scoped context.")


def register(app: typer.Typer) -> None:
    app.add_typer(threads_app, name="threads")


@threads_app.callback(invoke_without_command=True)
def list_threads(
    ctx: typer.Context,
    active: bool = typer.Option(False, "--active", help="Show only threads active in the last 24 hours."),
    conflicts: bool = typer.Option(False, "--conflicts", help="Show only threads with same-branch/worktree overlap."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    root = _root()
    rows = _latest_rows(list_thread_rows(root, active_only=active))
    if conflicts:
        rows = _rows_with_conflicts(root, rows)
    if json_output:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        console.print("[yellow]No AgentPack thread records found.[/]")
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    table.add_column("thread")
    table.add_column("status")
    table.add_column("branch")
    table.add_column("updated")
    table.add_column("task", max_width=50)
    table.add_column("overlap", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("thread_id") or ""),
            str(row.get("status") or "unknown"),
            str(row.get("branch") or ""),
            str(row.get("updated_at") or ""),
            str(row.get("task") or ""),
            str(row.get("conflict_count") or 0),
        )
    console.print(table)


@threads_app.command("archive")
def archive_thread(
    thread_id: str = typer.Argument(..., help="Thread id to mark done."),
    summary: str = typer.Option("Archived by agentpack threads archive.", "--summary", help="Task state summary."),
) -> None:
    root = _root()
    thread_id = sanitize_thread_id(thread_id)
    latest = _latest_row_for(root, thread_id) or {}
    row = build_thread_index_row(
        root=root,
        thread_id=thread_id,
        task=str(latest.get("task") or ""),
        branch=str(latest.get("branch") or git.current_branch(root) or ""),
        selected_files=list(latest.get("selected_files") or []),
        dirty_files=list(latest.get("dirty_files") or []),
        status="done",
    )
    append_thread_index(root, row)
    scoped = thread_paths(root, thread_id)
    assert scoped is not None
    scoped.task_state.parent.mkdir(parents=True, exist_ok=True)
    scoped.task_state.write_text(f"Status: done\nSummary: {summary.strip()}\n", encoding="utf-8")
    console.print(f"[green]✓[/] Archived thread {thread_id}")


@threads_app.command("prune")
def prune_threads(
    older_than: str = typer.Option("7d", "--older-than", help="Age threshold, e.g. 7d, 24h."),
    yes: bool = typer.Option(False, "--yes", help="Delete matching thread directories."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    root = _root()
    cutoff = datetime.now(timezone.utc) - _parse_duration(older_than)
    rows = _latest_rows(list_thread_rows(root))
    candidates: list[dict[str, Any]] = []
    for row in rows:
        updated = _parse_datetime(row.get("updated_at"))
        thread_id = str(row.get("thread_id") or "")
        scoped = thread_paths(root, thread_id)
        if not scoped or not scoped.base.exists() or updated is None or updated >= cutoff:
            continue
        candidates.append({"thread_id": thread_id, "path": str(scoped.base.relative_to(root)), "updated_at": row.get("updated_at")})
        if yes:
            shutil.rmtree(scoped.base)
    if json_output:
        typer.echo(json.dumps({"deleted": yes, "threads": candidates}, indent=2, sort_keys=True))
        return
    verb = "Deleted" if yes else "Would delete"
    console.print(f"[green]✓[/] {verb} {len(candidates)} thread director{'y' if len(candidates) == 1 else 'ies'}.")
    if not yes and candidates:
        console.print("  Re-run with [bold]--yes[/] to delete.")
    for item in candidates[:20]:
        console.print(f"  {item['thread_id']}  {item['path']}  {item['updated_at']}")


def _latest_row_for(root: Path, thread_id: str) -> dict[str, Any] | None:
    return next((row for row in _latest_rows(list_thread_rows(root)) if row.get("thread_id") == thread_id), None)


def _latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        thread_id = str(row.get("thread_id") or "")
        if not thread_id:
            continue
        previous = latest.get(thread_id)
        if previous is None or (_parse_datetime(row.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)) > (
            _parse_datetime(previous.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)
        ):
            latest[thread_id] = row
    return sorted(latest.values(), key=lambda row: str(row.get("updated_at") or ""), reverse=True)


def _rows_with_conflicts(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        context = detect_conflicts(root, row)
        conflicts = context.get("conflicts") or []
        if conflicts:
            item = dict(row)
            item["conflicts"] = conflicts
            item["conflict_count"] = len(conflicts)
            result.append(item)
    return result


def _parse_duration(value: str) -> timedelta:
    raw = value.strip().lower()
    if raw.endswith("h"):
        return timedelta(hours=max(0, int(raw[:-1] or "0")))
    if raw.endswith("d"):
        return timedelta(days=max(0, int(raw[:-1] or "0")))
    return timedelta(days=max(0, int(raw or "0")))


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
