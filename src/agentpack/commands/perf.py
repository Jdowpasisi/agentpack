from __future__ import annotations

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import _root, console
from agentpack.core.config import load_config
from agentpack.session.events import read_events, summarize_events


def register(app: typer.Typer) -> None:
    @app.command()
    def perf(
        history: int = typer.Option(0, "--history", help="Show the last N runtime events."),
        json_output: bool = typer.Option(False, "--json", help="Print scorecard as JSON."),
    ) -> None:
        """Show local runtime scorecard for AgentPack."""
        root = _root()
        cfg = load_config(root)
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
