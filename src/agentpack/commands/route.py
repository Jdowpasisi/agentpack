from __future__ import annotations

import typer

from agentpack.commands._shared import _root, console
from agentpack.router.prompt_builder import render_plain
from agentpack.router.service import RouteService


def register(app: typer.Typer) -> None:
    @app.command("route")
    def route_task(
        task: str = typer.Option(..., "--task", help="Developer task to route."),
        output_format: str = typer.Option("plain", "--format", help="Output format: plain|json."),
    ) -> None:
        """Route a task to relevant files, rules, skills, and command suggestions."""
        if output_format not in {"plain", "json"}:
            console.print("[red]Invalid format. Use plain|json.[/]")
            raise typer.Exit(1)
        try:
            result = RouteService().route_task(_root(), task)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc

        if output_format == "json":
            typer.echo(result.model_dump_json(indent=2))
        else:
            console.print(render_plain(result))
