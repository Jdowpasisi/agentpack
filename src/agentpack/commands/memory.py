from __future__ import annotations

import json
from collections import Counter

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import _root, console
from agentpack.core.config import load_config
from agentpack.session.references import merge_issue_reference_objects, merge_issue_references
from agentpack.session.events import read_events


def register(app: typer.Typer) -> None:
    @app.command()
    def memory(json_output: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
        """Show local cross-agent task memory from events and learning artifacts."""
        root = _root()
        cfg = load_config(root)
        events = read_events(root, output_path=cfg.runtime.session_events_output, limit=500)
        tasks = [str(event.get("task")) for event in events if event.get("task")]
        concepts = Counter(
            concept
            for event in events
            for concept in (event.get("concepts") or [])
            if isinstance(concept, str)
        )
        issue_references = merge_issue_references(
            ref
            for event in events
            for ref in (event.get("issue_references") or [])
            if isinstance(ref, str)
        )
        top_issue_references = Counter(
            ref
            for event in events
            for ref in (event.get("issue_references") or [])
            if isinstance(ref, str)
        ).most_common(20)
        issue_reference_details = merge_issue_reference_objects(
            item
            for event in events
            for item in (event.get("issue_reference_details") or [])
            if isinstance(item, dict)
        )
        payload = {
            "recent_tasks": tasks[-20:],
            "recent_issue_references": issue_references[-20:],
            "issue_reference_details": [item.to_dict() for item in issue_reference_details[-20:]],
            "top_issue_references": top_issue_references,
            "top_concepts": concepts.most_common(20),
            "event_count": len(events),
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
            return
        table = Table(title="AgentPack Memory", box=box.SIMPLE, show_header=True, padding=(0, 1))
        table.add_column("kind", style="dim")
        table.add_column("value")
        table.add_row("events", str(len(events)))
        for task in tasks[-10:]:
            table.add_row("task", task)
        for ref in issue_references[-10:]:
            table.add_row("issue", ref)
        for item in issue_reference_details[-10:]:
            label = item.ref
            if item.title:
                label += f" — {item.title}"
            if item.state:
                label += f" ({item.state})"
            table.add_row("issue detail", label)
        for concept, count in concepts.most_common(10):
            table.add_row("concept", f"{concept} ({count})")
        console.print(table)
