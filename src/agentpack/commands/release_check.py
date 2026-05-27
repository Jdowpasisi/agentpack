from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from agentpack.commands._shared import console, _root


@dataclass
class StageResult:
    name: str
    command: str
    status: str
    duration_s: float
    returncode: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "returncode": self.returncode,
            "detail": self.detail,
        }


def register(app: typer.Typer) -> None:
    @app.command("release-check")
    def release_check(
        skip_benchmark: bool = typer.Option(False, "--skip-benchmark", help="Skip public benchmark release gate."),
        skip_build: bool = typer.Option(False, "--skip-build", help="Skip wheel/sdist build."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Run release readiness checks without mutating tracked files."""
        root = _root()
        stages: list[StageResult] = []
        stages.append(_check_changelog(root))
        stages.append(_run_stage(root, "version-sync", ["node", "npm/test/version-sync.test.js"]))
        stages.append(_run_stage(root, "pytest", [sys.executable, "-m", "pytest", "-q"]))
        stages.append(_run_stage(root, "npm-launcher-tests", ["node", "npm/test/launcher.test.js"]))
        if not skip_build:
            with tempfile.TemporaryDirectory(prefix="agentpack-build-") as out_dir:
                stages.append(_run_stage(root, "build", [sys.executable, "-m", "build", "--outdir", out_dir]))
        if not skip_benchmark:
            stages.append(_run_stage(root, "benchmark-release-gate", [sys.executable, "-m", "agentpack.cli", "benchmark", "--release-gate", "--no-public-table"]))

        failed = [stage for stage in stages if stage.status != "passed"]
        if json_output:
            typer.echo(json.dumps({"passed": not failed, "stages": [stage.as_dict() for stage in stages]}, indent=2, sort_keys=True))
        else:
            for stage in stages:
                marker = "[green]✓[/]" if stage.status == "passed" else "[red]✗[/]"
                console.print(f"{marker} {stage.name}: {stage.status} ({stage.duration_s:.2f}s)")
                if stage.detail and stage.status != "passed":
                    console.print(f"  {stage.detail}")
                if stage.status != "passed":
                    console.print(f"  rerun: [bold]{stage.command}[/]")
        if failed:
            raise typer.Exit(1)


def _check_changelog(root: Path) -> StageResult:
    started = time.perf_counter()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    current = version.group(1) if version else ""
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8") if (root / "CHANGELOG.md").exists() else ""
    ok = bool(current and f"## [{current}]" in changelog)
    return StageResult(
        name="changelog",
        command="grep CHANGELOG.md",
        status="passed" if ok else "failed",
        duration_s=time.perf_counter() - started,
        returncode=0 if ok else 1,
        detail="" if ok else f"Missing CHANGELOG.md entry for {current or 'unknown version'}",
    )


def _run_stage(root: Path, name: str, command: list[str]) -> StageResult:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    except OSError as exc:
        return StageResult(name=name, command=" ".join(command), status="failed", duration_s=time.perf_counter() - started, returncode=1, detail=str(exc))
    output = (result.stderr or result.stdout).strip().splitlines()
    return StageResult(
        name=name,
        command=" ".join(command),
        status="passed" if result.returncode == 0 else "failed",
        duration_s=time.perf_counter() - started,
        returncode=result.returncode,
        detail=output[-1] if output else "",
    )
