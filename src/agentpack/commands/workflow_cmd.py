from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import typer

from agentpack.commands._shared import console, _root, run_refresh
from agentpack.core.config import load_config
from agentpack.core.loop_protocol import (
    LoopCommandResult,
    dry_run_plan,
    initialize_loop,
    run_loop,
)
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
        run_loop_requested: bool = typer.Option(False, "--run", help="Run the configured Ralph Loop after preparing context."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan Ralph Loop execution without running the configured runner."),
        runner: str = typer.Option("", "--runner", help="Generic shell command for the Ralph Loop runner."),
        max_iterations: int = typer.Option(0, "--max-iterations", help="Override [loop].max_iterations for this run."),
        verify: list[str] = typer.Option([], "--verify", help="Verification command for Ralph Loop. Repeatable."),
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
        if stages[-1]["returncode"] == 0 and not no_next and not run_loop_requested and not dry_run:
            stages.append(_run("next", cli_module_argv("next"), root))
        if stages[-1]["returncode"] != 0:
            _finish(stages, json_output)

        loop_plan = None
        loop_summary = None
        if run_loop_requested or dry_run:
            cfg = load_config(root)
            state = initialize_loop(
                root,
                task_text,
                cfg.loop,
                runner_override=runner,
                max_iterations_override=max_iterations,
                verification_overrides=list(verify) if verify else None,
            )
            if dry_run:
                loop_plan = dry_run_plan(root, state).model_dump(mode="json")
                _finish(stages, json_output, loop_plan=loop_plan)
                return
            if not state.runner:
                console.print("[red]Ralph Loop runner missing.[/] Set [loop].runner or pass --runner.")
                raise typer.Exit(1)
            loop_summary = run_loop(
                root,
                state,
                refresh=lambda: _refresh_loop_context(root, agent, mode, budget, resolve_thread_option(thread)),
            ).model_dump(mode="json")
            if loop_summary["status"] != "ready_to_finish":
                _finish(stages, json_output, loop_summary=loop_summary)
                raise typer.Exit(1)
        _finish(stages, json_output, loop_plan=loop_plan, loop_summary=loop_summary)

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


def _finish(
    stages: list[dict[str, Any]],
    json_output: bool,
    *,
    loop_plan: dict[str, Any] | None = None,
    loop_summary: dict[str, Any] | None = None,
) -> None:
    passed = all(stage["returncode"] == 0 for stage in stages)
    if json_output:
        payload: dict[str, Any] = {"passed": passed, "stages": stages}
        if loop_plan is not None:
            payload["loop_plan"] = loop_plan
        if loop_summary is not None:
            payload["loop_summary"] = loop_summary
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for stage in stages:
            marker = "[green]✓[/]" if stage["returncode"] == 0 else "[red]✗[/]"
            console.print(f"{marker} {stage['name']}")
            if stage["returncode"] != 0:
                console.print(f"  rerun: [bold]{stage['command']}[/]")
                if stage.get("detail"):
                    console.print(f"  [dim]{stage['detail']}[/]")
        if loop_plan is not None:
            console.print(f"[green]✓[/] Ralph Loop dry run: {loop_plan['next_action']}")
        if loop_summary is not None:
            marker = "[green]✓[/]" if loop_summary.get("status") == "ready_to_finish" else "[yellow]![/]"
            console.print(f"{marker} Ralph Loop {loop_summary.get('status')}: {loop_summary.get('reason') or loop_summary.get('next_command')}")
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


def _refresh_loop_context(root: Path, agent: str, mode: str, budget: int, thread_id: str | None) -> LoopCommandResult:
    stats = run_refresh(root, agent, mode, budget, thread_id=thread_id)
    if stats is None:
        return LoopCommandResult(command="agentpack guard --repair-stale --refresh-context", returncode=1, output_excerpt="context refresh failed")
    return LoopCommandResult(command="agentpack guard --repair-stale --refresh-context", returncode=0, output_excerpt=json.dumps(stats, sort_keys=True))
