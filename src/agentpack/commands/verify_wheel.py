from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import typer

from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command("verify-wheel")
    def verify_wheel(
        wheel: str = typer.Option("", "--wheel", help="Wheel path to verify. Defaults to latest dist/*.whl after building."),
        skip_build: bool = typer.Option(False, "--skip-build", help="Use an existing wheel without building first."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Install a built wheel in a temp venv and run the public benchmark gate."""
        result = run_verify_wheel(wheel=wheel, skip_build=skip_build)
        if json_output:
            typer.echo(json.dumps(result, indent=2, sort_keys=True))
        else:
            for stage in result["stages"]:
                marker = "[green]✓[/]" if stage["returncode"] == 0 else "[red]✗[/]"
                console.print(f"{marker} {stage['name']}")
        if not result["passed"]:
            raise typer.Exit(1)


def run_verify_wheel(*, wheel: str = "", skip_build: bool = False) -> dict[str, Any]:
    root = _root()
    stages: list[dict[str, Any]] = []
    if not skip_build:
        stages.append(_run(root, "build", [sys.executable, "-m", "build"]))
        if stages[-1]["returncode"] != 0:
            return {"passed": False, "stages": stages}
    wheel_path = Path(wheel) if wheel else _latest_wheel(root)
    if not wheel_path or not wheel_path.exists():
        return {"passed": False, "stages": stages + [{"name": "wheel", "command": "find dist/*.whl", "returncode": 1, "detail": "no wheel found"}]}
    with tempfile.TemporaryDirectory(prefix="agentpack-wheel-") as tmp:
        venv = Path(tmp) / "venv"
        stages.append(_run(root, "venv", [sys.executable, "-m", "venv", str(venv)]))
        pip = venv / ("Scripts/pip.exe" if sys.platform.startswith("win") else "bin/pip")
        agentpack = venv / ("Scripts/agentpack.exe" if sys.platform.startswith("win") else "bin/agentpack")
        if stages[-1]["returncode"] == 0:
            stages.append(_run(root, "install-wheel", [str(pip), "install", str(wheel_path)]))
        if stages[-1]["returncode"] == 0:
            stages.append(_run(root, "benchmark-release-gate", [str(agentpack), "benchmark", "--release-gate", "--no-public-table"]))
    return {"passed": all(stage["returncode"] == 0 for stage in stages), "stages": stages, "wheel": str(wheel_path)}


def _latest_wheel(root: Path) -> Path | None:
    wheels = sorted((root / "dist").glob("agentpack_cli-*.whl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return wheels[0] if wheels else None


def _run(root: Path, name: str, command: list[str]) -> dict[str, Any]:
    if not shutil.which(command[0]) and not Path(command[0]).exists():
        return {"name": name, "command": " ".join(command), "returncode": 1, "detail": f"{command[0]} not found"}
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    return {
        "name": name,
        "command": " ".join(command),
        "returncode": result.returncode,
        "detail": ((result.stderr or result.stdout).strip().splitlines() or [""])[-1],
    }
