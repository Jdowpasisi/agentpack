from __future__ import annotations

import json
from typing import Any

import typer

from agentpack.commands._shared import console, _root

ci_app = typer.Typer(help="Generate CI automation for AgentPack workflows.")


def register(app: typer.Typer) -> None:
    app.add_typer(ci_app, name="ci")


@ci_app.command("init")
def init_ci(
    force: bool = typer.Option(False, "--force", help="Overwrite an existing workflow."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Write a GitHub Actions workflow for AgentPack checks."""
    root = _root()
    path = root / ".github" / "workflows" / "agentpack.yml"
    payload: dict[str, Any] = {"path": str(path.relative_to(root)), "written": False, "overwritten": False}
    if path.exists() and not force:
        payload["reason"] = "workflow exists; pass --force to overwrite"
        if json_output:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
            return
        console.print(f"[yellow]Workflow already exists:[/] {payload['path']}")
        console.print("Run [bold]agentpack ci init --force[/] to overwrite it.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload["overwritten"] = path.exists()
    path.write_text(_workflow_yaml(), encoding="utf-8")
    payload["written"] = True
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"[green]✓[/] Wrote {payload['path']}")


def _workflow_yaml() -> str:
    return """name: AgentPack

on:
  pull_request:
  push:
    branches: [main]

jobs:
  dev-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: python -m pip install -e ".[dev]"
      - run: python -m agentpack.cli dev-check

  loop-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[dev]"
      - run: python -m agentpack.cli loop-smoke --json

  release-gate:
    runs-on: ubuntu-latest
    if: github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: python -m pip install -e ".[dev]" build
      - run: python -m agentpack.cli release-check --profile auto
"""
