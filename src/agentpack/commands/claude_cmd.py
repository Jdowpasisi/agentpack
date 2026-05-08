from __future__ import annotations

import hashlib
import shutil
import subprocess

import typer

from agentpack.commands._shared import console, _root
from agentpack.commands.session import _run_refresh, _now_iso
from agentpack.session.state import CONTEXT_FILE, TASK_FILE, load_session, log_activity, save_session


def register(app: typer.Typer) -> None:
    @app.command("claude")
    def claude_cmd() -> None:
        """Launch Claude CLI with the current AgentPack context."""
        root = _root()
        state = load_session(root)

        if state is None or not state.active:
            console.print("[yellow]No active session.[/]")
            console.print("Start one with: [bold]agentpack session start[/]")
            raise typer.Exit(1)

        console.print("Session active. Refreshing context...")
        result = _run_refresh(root, state.agent, state.mode, budget=0)
        if result:
            console.print(
                f"[green]✓[/] refreshed: {result['files']} files, "
                f"{result['tokens'] / 1000:.1f}k tokens"
            )
            state.last_refresh_at = _now_iso()
            state.refresh_count += 1
            task_path = root / TASK_FILE
            if task_path.exists():
                state.last_task_hash = hashlib.sha256(task_path.read_bytes()).hexdigest()[:16]
            save_session(root, state)
            log_activity(root, f"claude cmd — {result['files']} files, {result['tokens']:,} tokens")
        else:
            console.print("[red]Refresh failed — proceeding with existing context if available.[/]")

        context_path = root / CONTEXT_FILE
        console.print(f"\nContext ready: [bold]{context_path}[/]\n")

        claude_bin = shutil.which("claude")
        if claude_bin:
            console.print("Launching Claude CLI...")
            console.print("[dim](Claude reads .agentpack/context.md via CLAUDE.md or /agentpack)[/]\n")
            subprocess.run(["claude"])
        else:
            console.print("[yellow]Claude CLI not found.[/]")
            console.print("Install: https://claude.ai/download")
            console.print(f"\nOnce installed, run [bold]claude[/] and use: [bold]{context_path}[/]")
