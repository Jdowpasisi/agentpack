from __future__ import annotations

import shutil
import subprocess

import typer

from agentpack.commands._shared import console, _root, run_refresh, _now_iso, _file_hash
from agentpack.session.state import CONTEXT_FILE, TASK_FILE, load_session, log_activity, save_session


def register(app: typer.Typer) -> None:
    @app.command("claude")
    def claude_cmd() -> None:
        """Launch Claude CLI with the current AgentPack context."""
        root = _root()
        state = load_session(root)

        if state is None or not state.active:
            console.print("[yellow]No active session. Run: agentpack init[/]")
            raise typer.Exit(1)

        console.print("Session active. Refreshing context...")
        result = run_refresh(root, state.agent, state.mode, budget=0)
        if result:
            console.print(
                f"[green]✓[/] refreshed: {result['files']} files, "
                f"{result['tokens'] / 1000:.1f}k tokens"
            )
            state.last_refresh_at = _now_iso()
            state.refresh_count += 1
            state.last_task_hash = _file_hash(root / TASK_FILE)
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
