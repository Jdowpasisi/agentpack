from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich import box

from agentpack.core import git
from agentpack.application.pack_service import PackRequest, PackService, PackResult
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def pack(
        agent: str = typer.Option("claude", "--agent", help="Target agent (claude|cursor|windsurf|codex|generic)."),
        task: str = typer.Option("auto", "--task", help="Task description, or 'auto' to infer from git."),
        mode: str = typer.Option("balanced", "--mode", help="Budget mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = use config default)."),
        since: Optional[str] = typer.Option(None, "--since", help="Git ref to compare against (e.g. HEAD~1, main)."),
        print_output: bool = typer.Option(False, "--print", help="Print context to stdout."),
        refresh: bool = typer.Option(False, "--refresh", help="Rebuild summaries before packing."),
        summary_provider: str = typer.Option("offline", "--summary-provider", help="Summary provider (offline|claude)."),
        watch: bool = typer.Option(False, "--watch", help="Watch for file changes and re-pack automatically."),
        session: bool = typer.Option(False, "--session", help="Keep re-packing on changes for the whole session (alias for --watch)."),
    ) -> None:
        """Generate a context pack for an AI coding agent."""
        if mode not in ("minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
            raise typer.Exit(1)

        resolved_task = _resolve_task(task)

        if watch or session:
            _pack_watch(agent=agent, task=resolved_task, mode=mode, budget=budget,
                        since=since, summary_provider=summary_provider)
            return

        result = PackService().run(PackRequest(
            root=_root(),
            agent=agent,
            task=resolved_task,
            mode=mode,
            budget=budget,
            since=since,
            refresh=refresh,
            summary_provider=summary_provider,
        ))
        _print_pack_summary(result)
        if print_output:
            print(result.out_path.read_text())


def _resolve_task(task: str) -> str:
    if task != "auto":
        return task
    inferred = git.infer_task_from_git(_root())
    console.print(f"[dim]Auto task: {inferred}[/]")
    return inferred


def _print_pack_summary(result: PackResult) -> None:
    out_path = result.out_path
    selected = result.pack.selected_files
    packed_tokens = result.packed_tokens
    raw_tokens = result.raw_tokens
    saving_pct = result.saving_pct
    changed_files = result.changed_files
    task = result.pack.task
    since = None  # since is not stored in PackResult; shown via changed_files

    stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats.add_column(style="dim")
    stats.add_column(justify="right", style="bold")
    stats.add_row("packed tokens", f"{packed_tokens:,}")
    stats.add_row("raw tokens", f"{raw_tokens:,}")
    stats.add_row("saving", f"[green]{saving_pct:.1f}%[/]")

    MODE_STYLE = {"full": "green", "symbols": "yellow", "summary": "dim"}
    files_tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    files_tbl.add_column("file", style="dim", no_wrap=False, max_width=55)
    files_tbl.add_column("mode", justify="center", width=8)
    files_tbl.add_column("why", style="dim", max_width=30)

    changed_set = set(changed_files)
    for sf in selected[:20]:
        style = MODE_STYLE.get(sf.include_mode, "")
        changed_marker = " [red]●[/]" if sf.path in changed_set else ""
        files_tbl.add_row(
            f"{sf.path}{changed_marker}",
            f"[{style}]{sf.include_mode}[/]",
            sf.reasons[0] if sf.reasons else "",
        )
    if len(selected) > 20:
        files_tbl.add_row(f"[dim]... {len(selected) - 20} more[/]", "", "")

    if changed_files:
        changed_lines = "\n".join(f"  [red]●[/] {f}" for f in changed_files[:10])
        if len(changed_files) > 10:
            changed_lines += f"\n  [dim]... {len(changed_files) - 10} more[/]"
    else:
        changed_lines = "  [dim]none detected[/]"

    console.print()
    console.print(Panel(
        f"[bold cyan]{task}[/]",
        title="[bold green]✓ Context Pack Ready[/]",
        subtitle=f"[dim]{out_path}[/]",
        border_style="green",
        padding=(0, 1),
    ))
    console.print()
    console.print(Columns([stats, files_tbl], equal=False, expand=False))

    if changed_files:
        console.print(f"\n[bold]Changed files[/] ({len(changed_files)}):")
        console.print(changed_lines)

    console.print(f"\n[bold]Next step:[/]")
    console.print(f"  [bold white]claude < {out_path}[/]")
    console.print(f"  [dim]or: agentpack pack --task \"{task}\" --print | claude[/]")
    console.print()


def _pack_watch(
    agent: str,
    task: str,
    mode: str,
    budget: int,
    since: str | None,
    summary_provider: str,
) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        console.print("[red]watchdog is required for --watch mode.[/]")
        console.print("Install it: [bold]pip install watchdog[/]")
        raise typer.Exit(1)

    root = _root()
    console.print(f"[bold]Watch mode active.[/] Repacking on file changes... (Ctrl+C to stop)")
    console.print(f"  Task: {task}")

    def _run_pack() -> None:
        result = PackService().run(PackRequest(
            root=root, agent=agent, task=task, mode=mode, budget=budget,
            since=since, refresh=False, summary_provider=summary_provider,
        ))
        _print_pack_summary(result)

    _run_pack()

    _last_pack = [time.time()]
    _DEBOUNCE = 2.0

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):  # type: ignore[override]
            if event.is_directory:
                return
            path = str(event.src_path)
            if ".agentpack" in path:
                return
            now = time.time()
            if now - _last_pack[0] < _DEBOUNCE:
                return
            _last_pack[0] = now
            console.print(f"\n[dim]Change detected: {event.src_path}[/]")
            try:
                _run_pack()
            except Exception as e:
                console.print(f"[red]Pack error: {e}[/]")

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watch mode stopped.[/]")
    observer.join()
