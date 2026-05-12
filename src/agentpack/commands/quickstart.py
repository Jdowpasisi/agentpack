from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from agentpack.commands._shared import console, _root
from agentpack.session.state import TASK_FILE


_PLACEHOLDER_TASK = "Write or update the current coding task here."


def register(app: typer.Typer) -> None:
    @app.command()
    def quickstart(
        task: str = typer.Option("", "--task", help="Optional task to show or write into .agentpack/task.md."),
        mode: str = typer.Option("balanced", "--mode", help="Suggested mode (minimal|balanced|deep)."),
        write: bool = typer.Option(False, "--write", help="Write --task into .agentpack/task.md."),
    ) -> None:
        """Show the fastest useful path for a new repo."""
        if mode not in ("minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
            raise typer.Exit(1)
        if write and not task.strip():
            console.print("[red]--write requires --task.[/]")
            raise typer.Exit(1)

        root = _root()
        written = False
        if write:
            task_path = root / TASK_FILE
            task_path.parent.mkdir(parents=True, exist_ok=True)
            task_path.write_text(task.strip() + "\n", encoding="utf-8")
            written = True

        state = _quickstart_state(root, task.strip(), mode, written=written)

        console.print("\n[bold]AgentPack quickstart[/]")
        console.print(state["summary"])
        console.print()

        table = Table(show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Command")
        table.add_column("Why", style="dim")
        for i, (cmd, why) in enumerate(state["steps"], 1):
            table.add_row(str(i), f"[bold]{cmd}[/]", why)
        console.print(table)

        if state["notes"]:
            console.print()
            for note in state["notes"]:
                console.print(f"[dim]- {note}[/]")


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _task_status(root: Path) -> tuple[bool, str]:
    task_path = root / TASK_FILE
    if not task_path.exists():
        return False, ""
    text = task_path.read_text(encoding="utf-8").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        return False, ""
    first = lines[0]
    if _PLACEHOLDER_TASK in first:
        return False, first
    return True, first


def _quickstart_state(root: Path, task: str, mode: str, *, written: bool = False) -> dict[str, object]:
    initialized = (root / ".agentpack" / "config.toml").exists()
    has_task, current_task = _task_status(root)
    has_context = (root / ".agentpack" / "context.md").exists() or (root / ".agentpack" / "context.claude.md").exists()

    steps: list[tuple[str, str]] = []
    notes: list[str] = []

    if not initialized:
        steps.append((f"agentpack init --yes --mode {mode}", "create config, cache dir, session, and task file"))
    else:
        notes.append(".agentpack/config.toml already exists.")

    if written:
        notes.append(f"Saved task: {task}")
    elif task:
        steps.append((f"printf '%s\\n' {_shell_single_quote(task)} > .agentpack/task.md", "make ranking task-specific"))
    elif not has_task:
        steps.append(("edit .agentpack/task.md", "write one concrete task, e.g. 'fix auth token expiry'"))
    else:
        notes.append(f"Current task: {current_task}")

    steps.append(("agentpack pack --task auto", "generate the first focused context pack"))
    steps.append(("agentpack stats", "check compression, selected files, and token precision"))
    steps.append(("agentpack watch", "keep context fresh while you work"))
    steps.append(("agentpack benchmark --init", "start measuring selection quality on your own real tasks"))

    if has_context:
        notes.append("A context pack already exists; rerun pack after changing task text.")
    if not task and not has_task:
        notes.append("Specific tasks beat vague ones: include subsystem, symptom, and file/module names when known.")

    summary = "Fast path for a useful pack in about two minutes."
    if initialized and (has_task or written):
        summary = "Repo already has enough setup to pack useful context."

    return {"summary": summary, "steps": steps, "notes": notes}
