from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import typer

from agentpack.commands._shared import console, _root
from agentpack.core.thread_context import resolve_thread_option
from agentpack.integrations.platform import cli_module_argv


def register(app: typer.Typer) -> None:
    @app.command("work")
    def work(
        task_text: str = typer.Argument(..., help="Task text to start."),
        thread: str = typer.Option("", "--thread", help="Use thread-scoped task/context state."),
        agent: str = typer.Option("auto", "--agent", help="Agent to initialize and refresh for."),
        mode: str = typer.Option("balanced", "--mode", help="Pack/guard mode."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = config default)."),
        workspace: str = typer.Option("", "--workspace", help="Restrict pack to a monorepo workspace."),
        pack_only: bool = typer.Option(False, "--pack-only", help="Run pack directly instead of guard."),
        no_init: bool = typer.Option(False, "--no-init", help="Do not initialize the repo when .agentpack/config.toml is missing."),
        no_next: bool = typer.Option(False, "--no-next", help="Do not print next-step diagnostics after context refresh."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Initialize if needed, write a task, refresh context, and show next steps."""
        root = _root()
        stages: list[dict[str, Any]] = []
        if not no_init and not (root / ".agentpack" / "config.toml").exists():
            stages.append(_run("init", cli_module_argv("init", "--yes", "--agent", agent), root))
            if stages[-1]["returncode"] != 0:
                _finish(stages, json_output)

        start_args = ["start", task_text, "--agent", agent, "--mode", mode]
        if thread:
            start_args.extend(["--thread", thread])
        if budget:
            start_args.extend(["--budget", str(budget)])
        if workspace:
            start_args.extend(["--workspace", workspace])
        if pack_only:
            start_args.append("--pack-only")
        stages.append(_run("start", cli_module_argv(*start_args), root))
        if stages[-1]["returncode"] == 0 and not no_next:
            stages.append(_run("next", cli_module_argv("next"), root))
        _finish(stages, json_output)

    @app.command("finish")
    def finish(
        since: str = typer.Option("", "--since", help="Git ref for benchmark capture, e.g. main or HEAD~1."),
        task: str = typer.Option("", "--task", help="Task text for benchmark capture and completion summary."),
        thread: str = typer.Option("", "--thread", help="Use thread-scoped state."),
        summary: str = typer.Option("Finished by agentpack finish.", "--summary", help="Completion summary."),
        skip_checks: bool = typer.Option(False, "--skip-checks", help="Skip agentpack dev-check."),
        skip_diagnosis: bool = typer.Option(False, "--skip-diagnosis", help="Skip selection diagnosis write."),
        skip_benchmark_capture: bool = typer.Option(False, "--skip-benchmark-capture", help="Skip benchmark case capture."),
        archive_thread: bool = typer.Option(False, "--archive-thread", help="Archive the thread after marking state done."),
        allow_empty_capture: bool = typer.Option(False, "--allow-empty-capture", help="Allow benchmark capture with no expected files."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Run finish checks, capture benchmark evidence, and mark work done."""
        root = _root()
        stages: list[dict[str, Any]] = []
        if not skip_diagnosis:
            stages.append(_run("diagnose-selection", cli_module_argv("diagnose-selection", "--write"), root))
        if not skip_benchmark_capture and since:
            capture_task = task or _read_task(root, thread) or summary
            args = ["benchmark", "capture", "--since", since, "--task", capture_task]
            if allow_empty_capture:
                args.append("--allow-empty")
            stages.append(_run("benchmark-capture", cli_module_argv(*args), root))
        if stages and stages[-1]["returncode"] != 0:
            _finish(stages, json_output)
        if not skip_checks:
            stages.append(_run("dev-check", cli_module_argv("dev-check"), root))
        if stages and stages[-1]["returncode"] != 0:
            _finish(stages, json_output)

        state_args = ["state", "done", "--summary", summary]
        thread_id = resolve_thread_option(thread)
        if thread_id:
            state_args.extend(["--thread", thread_id])
        stages.append(_run("state-done", cli_module_argv(*state_args), root))
        if archive_thread and thread_id and stages[-1]["returncode"] == 0:
            stages.append(_run("threads-archive", cli_module_argv("threads", "archive", thread_id, "--summary", summary), root))
        _finish(stages, json_output)


def _run(name: str, command: list[str], root: Path) -> dict[str, Any]:
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    detail = ((result.stderr or result.stdout).strip().splitlines() or [""])[-1]
    return {
        "name": name,
        "command": " ".join(command),
        "returncode": result.returncode,
        "detail": detail,
    }


def _finish(stages: list[dict[str, Any]], json_output: bool) -> None:
    passed = all(stage["returncode"] == 0 for stage in stages)
    if json_output:
        typer.echo(json.dumps({"passed": passed, "stages": stages}, indent=2, sort_keys=True))
    else:
        for stage in stages:
            marker = "[green]✓[/]" if stage["returncode"] == 0 else "[red]✗[/]"
            console.print(f"{marker} {stage['name']}")
            if stage["returncode"] != 0:
                console.print(f"  rerun: [bold]{stage['command']}[/]")
                if stage.get("detail"):
                    console.print(f"  [dim]{stage['detail']}[/]")
    if not passed:
        raise typer.Exit(1)


def _read_task(root: Path, thread: str) -> str:
    thread_id = resolve_thread_option(thread)
    if thread_id:
        path = root / ".agentpack" / "threads" / thread_id / "task.md"
    else:
        path = root / ".agentpack" / "task.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
