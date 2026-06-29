from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

import typer

from agentpack.commands._shared import console, _root


@dataclass
class CheckStage:
    name: str
    command: list[str]


def register(app: typer.Typer) -> None:
    @app.command("dev-check")
    def dev_check(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Run the common local developer checks."""
        stages = [
            CheckStage("docs-check", [sys.executable, "-m", "pytest", "tests/test_docs_links.py", "-q"]),
            CheckStage("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
            CheckStage("mypy", [sys.executable, "-m", "mypy"]),
            CheckStage("pytest", [sys.executable, "-m", "pytest", "-q", "-m", "not slow"]),
            CheckStage("npm-version-sync", ["node", "npm/test/version-sync.test.js"]),
            CheckStage("npm-launcher", ["node", "npm/test/launcher.test.js"]),
        ]
        results = [_run(stage) for stage in stages]
        failed = [item for item in results if item["returncode"] != 0]
        if json_output:
            typer.echo(json.dumps({"passed": not failed, "stages": results}, indent=2, sort_keys=True))
        else:
            for item in results:
                marker = "[green]✓[/]" if item["returncode"] == 0 else "[red]✗[/]"
                console.print(f"{marker} {item['name']} ({item['duration_s']:.2f}s)")
                if item["returncode"] != 0:
                    if item["output_excerpt"]:
                        console.print(item["output_excerpt"])
                    console.print(f"  rerun: [bold]{item['command']}[/]")
        if failed:
            raise typer.Exit(1)


def _run(stage: CheckStage) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(stage.command, cwd=_root(), capture_output=True, text=True)
    output = (result.stdout + "\n" + result.stderr).strip()
    return {
        "name": stage.name,
        "command": " ".join(stage.command),
        "returncode": result.returncode,
        "duration_s": round(time.perf_counter() - started, 3),
        "detail": (output.splitlines() or [""])[-1],
        "output_excerpt": _output_excerpt(output) if result.returncode != 0 else "",
    }


def _output_excerpt(output: str, *, max_lines: int = 80) -> str:
    lines = output.splitlines()
    if len(lines) <= max_lines:
        excerpt = lines
    else:
        excerpt = ["... output truncated to final failing lines ...", *lines[-max_lines:]]
    return "\n".join(f"  {line}" for line in excerpt)
