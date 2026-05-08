from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root
from agentpack.session.state import (
    CONTEXT_FILE, COMPACT_FILE, TASK_FILE, SESSION_FILE,
    create_session, load_session, save_session, stop_session, log_activity,
)


def register(app: typer.Typer) -> None:
    session_app = typer.Typer(help="Manage AgentPack sessions.")
    app.add_typer(session_app, name="session")

    @session_app.command("start")
    def start(
        agent: str = typer.Option("auto", "--agent", help="Target agent (auto|claude|cursor|windsurf|codex|antigravity|generic)."),
        mode: str = typer.Option("balanced", "--mode", help="Pack mode (minimal|balanced|deep)."),
        task: str = typer.Option("", "--task", help="Initial task description."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = config default)."),
        silent: bool = typer.Option(False, "--silent", help="Suppress all output (for use in hooks/scripts)."),
    ) -> None:
        """Start a session: create state files and generate initial context."""
        root = _root()
        if silent:
            console.quiet = True
        state = create_session(root, agent=agent, mode=mode)

        if task:
            (root / TASK_FILE).write_text(f"# Current Task\n\n{task}\n", encoding="utf-8")

        console.print()
        console.print("[bold green]AgentPack session started.[/]")
        console.print()

        created: list[tuple[str, str]] = [
            (SESSION_FILE, "session state"),
            (TASK_FILE, "edit to set your task"),
        ]

        result = _run_refresh(root, state.agent, state.mode, budget)
        if result:
            created += [
                (CONTEXT_FILE, f"{result['files']} files, {result['tokens']:,} tokens"),
                (COMPACT_FILE, "compact protocol format"),
            ]
            log_activity(root, f"session started — {result['files']} files, {result['tokens']:,} tokens")
        else:
            created += [
                (CONTEXT_FILE, "will generate on first refresh"),
                (COMPACT_FILE, "will generate on first refresh"),
            ]
            log_activity(root, "session started (context generation deferred)")

        console.print("[bold]Created:[/]")
        for path, note in created:
            console.print(f"  [green]✓[/] {path}  [dim]{note}[/]")

        console.print()
        console.print("[bold]Next:[/]")
        console.print("  - Run [bold]agentpack watch[/] in another terminal to auto-refresh context.")
        console.print("  - Open your agent (Claude Code / Cursor / Windsurf / Codex / Antigravity) and ask your task normally.")
        console.print("  - To change the task: [bold]agentpack session refresh --task \"new task\"[/]")
        console.print()

    @session_app.command("stop")
    def stop() -> None:
        """Stop the current session."""
        root = _root()
        state = load_session(root)
        if state is None or not state.active:
            console.print("[yellow]No active session.[/]")
            raise typer.Exit(1)
        stop_session(root)
        log_activity(root, "session stopped")
        console.print("[dim]Session stopped.[/]")

    @session_app.command("status")
    def status() -> None:
        """Show current session status."""
        root = _root()
        state = load_session(root)
        if state is None:
            console.print("[yellow]No session found. Run: agentpack session start[/]")
            raise typer.Exit(1)

        tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        tbl.add_column(style="dim")
        tbl.add_column(style="bold")
        tbl.add_row("active", "[green]yes[/]" if state.active else "[red]no[/]")
        tbl.add_row("agent", state.agent)
        tbl.add_row("mode", state.mode)
        tbl.add_row("started", state.started_at or "—")
        tbl.add_row("last refresh", state.last_refresh_at or "—")
        tbl.add_row("refresh count", str(state.refresh_count))
        tbl.add_row("context", str(root / CONTEXT_FILE))
        console.print(tbl)

        context_path = root / CONTEXT_FILE
        if context_path.exists():
            from agentpack.core.token_estimator import estimate_tokens
            tokens = estimate_tokens(context_path.read_text(encoding="utf-8"))
            console.print(f"[dim]context size: ~{tokens:,} tokens[/]")

    @session_app.command("refresh")
    def refresh(
        task: str = typer.Option("", "--task", help="Override task for this refresh."),
        budget: int = typer.Option(0, "--budget", help="Token budget override."),
    ) -> None:
        """Refresh context pack for the current session."""
        root = _root()
        state = load_session(root)
        if state is None:
            console.print("[yellow]No session. Run: agentpack session start[/]")
            raise typer.Exit(1)

        if task:
            (root / TASK_FILE).write_text(f"# Current Task\n\n{task}\n", encoding="utf-8")

        result = _run_refresh(root, state.agent, state.mode, budget)
        if result:
            state.last_refresh_at = _now_iso()
            state.refresh_count += 1
            state.last_task_hash = _file_hash(root / TASK_FILE)
            save_session(root, state)
            log_activity(root, f"refreshed — {result['files']} files, {result['tokens']:,} tokens")
            console.print(f"[green]✓[/] refreshed: {result['files']} files, {result['tokens']:,} tokens, {result['saving']:.1f}% saving")
        else:
            console.print("[red]Refresh failed.[/]")
            raise typer.Exit(1)


def _run_refresh(
    root: Path,
    agent: str,
    mode: str,
    budget: int,
) -> Optional[dict]:
    """Run PackService and write context + compact files. Returns stats dict or None on error."""
    try:
        from agentpack.application.pack_service import PackService, PackRequest
        from agentpack.core import git
        from agentpack.renderers.compact import render_compact

        task_path = root / TASK_FILE
        if task_path.exists():
            raw = task_path.read_text(encoding="utf-8").strip()
            lines = [l for l in raw.splitlines() if l.strip() and not l.startswith("#")]
            task = lines[0].strip() if lines else ""
        else:
            task = ""

        if not task:
            if git.is_git_repo(root):
                task = git.infer_task_from_git(root)
            else:
                task = "Current branch changes and likely related files"

        result = PackService().run(PackRequest(
            root=root,
            agent=agent,
            task=task,
            mode=mode,
            budget=budget,
            since=None,
            refresh=False,
            summary_provider="offline",
        ))

        # Write readable context
        from agentpack.renderers.markdown import render_generic
        context_text = render_generic(result.pack)
        context_path = root / CONTEXT_FILE
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(context_text, encoding="utf-8")

        # Write compact context
        compact_text = render_compact(result.pack)
        compact_path = root / COMPACT_FILE
        compact_path.write_text(compact_text, encoding="utf-8")

        return {
            "files": len(result.pack.selected_files),
            "tokens": result.packed_tokens,
            "saving": result.saving_pct,
        }
    except Exception as e:
        console.print(f"[red]Error during refresh: {e}[/]")
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
