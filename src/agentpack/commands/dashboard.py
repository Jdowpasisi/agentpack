from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from agentpack.commands._shared import _atomic_write, _root, console
from agentpack.dashboard.collectors import build_project_dashboard_snapshot
from agentpack.dashboard.renderers import render_dashboard_html


def register(app: typer.Typer) -> None:
    @app.command()
    def dashboard(
        json_output: bool = typer.Option(False, "--json", help="Print normalized dashboard snapshot JSON."),
        open_browser: bool = typer.Option(False, "--open", help="Open the generated HTML dashboard."),
        output: str = typer.Option("", "--output", "-o", help="Dashboard HTML output path."),
    ) -> None:
        """Generate a local AgentPack dashboard."""
        root = _root()
        snapshot = build_project_dashboard_snapshot(root)
        if json_output:
            typer.echo(json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True))
            return

        out = root / (output or ".agentpack/dashboard.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out, render_dashboard_html(snapshot))
        console.print(f"[green]✓[/] Wrote [bold]{out}[/]")
        if open_browser:
            _open_file(out)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["cmd", "/c", "start", "", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
