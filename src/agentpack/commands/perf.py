from __future__ import annotations

import os
import time

import typer
from rich.table import Table
from rich import box

from agentpack.application.pack_service import PackPlanner, PackRequest
from agentpack.commands._shared import _root, console
from agentpack.core.config import load_config
from agentpack.core.task_freshness import read_task_md
from agentpack.core.token_estimator import estimate_tokens
from agentpack.session.events import read_events, summarize_events


def register(app: typer.Typer) -> None:
    @app.command()
    def perf(
        history: int = typer.Option(0, "--history", help="Show the last N runtime events."),
        measure_pack: bool = typer.Option(False, "--measure-pack", help="Measure pack planning with broad context off/on."),
        task: str = typer.Option("auto", "--task", help="Task text for --measure-pack, or auto for .agentpack/task.md."),
        mode: str = typer.Option("balanced", "--mode", help="Pack mode for --measure-pack."),
        repeat: int = typer.Option(1, "--repeat", min=1, help="Number of planning runs per profile."),
        json_output: bool = typer.Option(False, "--json", help="Print scorecard as JSON."),
    ) -> None:
        """Show local runtime scorecard for AgentPack."""
        root = _root()
        cfg = load_config(root)
        if measure_pack:
            rows = _measure_pack_profiles(root, task=task, mode=mode, repeat=repeat)
            if json_output:
                import json

                typer.echo(json.dumps({"pack_profiles": rows}, indent=2))
                return
            table = Table(title="AgentPack Pack Profile", box=box.SIMPLE, show_header=True, padding=(0, 1))
            table.add_column("profile")
            table.add_column("avg ms", justify="right")
            table.add_column("selected", justify="right")
            table.add_column("repo map tok", justify="right")
            table.add_column("broad tok", justify="right")
            table.add_column("broad modules", justify="right")
            table.add_column("context intent")
            for row in rows:
                table.add_row(
                    row["profile"],
                    f"{row['avg_ms']:.1f}",
                    str(row["selected_files"]),
                    str(row["repo_map_tokens"]),
                    str(row["broad_context_tokens"]),
                    str(row["broad_modules"]),
                    row["context_intent"],
                )
            console.print(table)
            return
        events = read_events(root, output_path=cfg.runtime.session_events_output, limit=max(200, history))
        summary = summarize_events(events)
        if json_output:
            import json

            typer.echo(json.dumps({"summary": summary, "history": events[-history:] if history > 0 else []}, indent=2))
            return
        table = Table(title="AgentPack Perf", box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(justify="right", style="bold")
        table.add_row("events", f"{summary['events']:,}")
        table.add_row("raw tokens packed", f"{summary['raw_tokens']:,}")
        table.add_row("packed tokens", f"{summary['packed_tokens']:,}")
        table.add_row("estimated saved tokens", f"{summary['estimated_saved_tokens']:,}")
        table.add_row("retrievals", f"{summary['retrievals']:,}")
        table.add_row("output compressions", f"{summary['output_compressions']:,}")
        console.print(table)
        if history > 0:
            history_table = Table(title=f"Recent Events ({min(history, len(events))})", box=box.SIMPLE)
            history_table.add_column("time", style="dim")
            history_table.add_column("type", style="bold")
            history_table.add_column("detail")
            for event in events[-history:]:
                history_table.add_row(
                    str(event.get("timestamp") or "")[:19],
                    str(event.get("type") or "unknown"),
                    _event_detail(event),
                )
            console.print(history_table)


def _event_detail(event: dict) -> str:
    event_type = str(event.get("type") or "")
    if event_type == "pack":
        return (
            f"{event.get('packed_tokens', 0)} / {event.get('raw_tokens', 0)} tokens; "
            f"{event.get('selected_files', 0)} files"
        )
    if event_type == "retrieve":
        return str(event.get("path") or event.get("block_id") or event.get("mode") or "")
    if event_type == "compress_output":
        return f"{event.get('kind', 'auto')} {event.get('input_tokens', 0)} -> {event.get('output_tokens', 0)} tokens"
    if event_type == "learn":
        return f"{event.get('changed_files', 0)} changed; {event.get('selected_misses', 0)} misses"
    if event_type == "learn_feedback":
        return str(event.get("feedback") or "")
    if event_type == "wrap":
        return str(event.get("agent") or "")
    return ""


def _measure_pack_profiles(root, *, task: str, mode: str, repeat: int) -> list[dict]:
    task_text = _resolve_perf_task(root, task)
    rows: list[dict] = []
    previous = os.environ.get("AGENTPACK_BROAD_CONTEXT")
    try:
        for profile, setting in (("broad-off", "off"), ("broad-on", "on")):
            os.environ["AGENTPACK_BROAD_CONTEXT"] = setting
            durations: list[float] = []
            last_plan = None
            for _ in range(repeat):
                started = time.perf_counter()
                last_plan = PackPlanner().plan(PackRequest(
                    root=root,
                    agent="generic",
                    task=task_text,
                    mode=mode,
                    budget=0,
                    since=None,
                    refresh=False,
                    task_source="perf",
                ))
                durations.append((time.perf_counter() - started) * 1000)
            broad_tokens = 0
            broad_modules = 0
            if last_plan and last_plan.broad_context:
                broad_tokens = estimate_tokens(last_plan.broad_context.model_dump_json())
                broad_modules = len(last_plan.broad_context.module_summaries)
            rows.append({
                "profile": profile,
                "avg_ms": sum(durations) / len(durations),
                "selected_files": len(last_plan.selected) if last_plan else 0,
                "repo_map_tokens": estimate_tokens(last_plan.repo_map) if last_plan else 0,
                "broad_context_tokens": broad_tokens,
                "broad_modules": broad_modules,
                "context_intent": last_plan.context_intent if last_plan else "",
            })
    finally:
        if previous is None:
            os.environ.pop("AGENTPACK_BROAD_CONTEXT", None)
        else:
            os.environ["AGENTPACK_BROAD_CONTEXT"] = previous
    return rows


def _resolve_perf_task(root, task: str) -> str:
    if task != "auto":
        return task
    text = read_task_md(root)
    return text or "measure AgentPack pack performance"
