from __future__ import annotations

import json
import subprocess
from typing import Any

import typer

from agentpack.commands._shared import console, _root
from agentpack.commands.verify_wheel import run_verify_wheel
from agentpack.integrations.platform import cli_module_argv

release_app = typer.Typer(help="Release preparation workflows.")


def register(app: typer.Typer) -> None:
    app.add_typer(release_app, name="release")


@release_app.command("prepare")
def prepare_release(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Run release-check, publish benchmark evidence, and verify the built wheel."""
    root = _root()
    stages: list[dict[str, Any]] = []
    stages.append(_run("release-check", cli_module_argv("release-check", "--check-release-branch", "--check-registry")))
    if stages[-1]["returncode"] == 0:
        stages.append(_run("benchmark-public-table", cli_module_argv("benchmark", "--release-gate")))
    if stages[-1]["returncode"] == 0:
        wheel_result = run_verify_wheel()
        stages.extend({**stage, "name": f"verify-wheel:{stage['name']}"} for stage in wheel_result["stages"])
    passed = all(stage["returncode"] == 0 for stage in stages)
    payload = {"passed": passed, "stages": stages, "root": str(root)}
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for stage in stages:
            marker = "[green]✓[/]" if stage["returncode"] == 0 else "[red]✗[/]"
            console.print(f"{marker} {stage['name']}")
        if passed:
            console.print("[bold green]Release preparation complete.[/]")
    if not passed:
        raise typer.Exit(1)


def _run(name: str, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=_root(), capture_output=True, text=True)
    return {
        "name": name,
        "command": " ".join(command),
        "returncode": result.returncode,
        "detail": ((result.stderr or result.stdout).strip().splitlines() or [""])[-1],
    }
