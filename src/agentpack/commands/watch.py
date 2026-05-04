from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import typer

from agentpack.commands._shared import console, _root
from agentpack.session.state import TASK_FILE, load_session, save_session, log_activity


_IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "__pycache__"}
_IGNORE_NAMES = {"context.md", "context.compact.md"}


def register(app: typer.Typer) -> None:
    @app.command()
    def watch(
        agent: str = typer.Option("", "--agent", help="Agent override (uses session agent if not set)."),
        mode: str = typer.Option("", "--mode", help="Mode override (uses session mode if not set)."),
        budget: int = typer.Option(0, "--budget", help="Token budget override."),
        debounce: float = typer.Option(2.0, "--debounce", help="Seconds to wait after last change before refresh."),
    ) -> None:
        """Watch for file changes and refresh context automatically."""
        root = _root()
        state = load_session(root)

        effective_agent = agent or (state.agent if state else "generic")
        effective_mode = mode or (state.mode if state else "balanced")

        if state is None:
            console.print("[yellow]No session found — watching in stateless mode.[/]")
            console.print("[dim]Run 'agentpack session start' for full session support.[/]")

        console.print()
        console.print("[bold]AgentPack watch active.[/]")
        console.print("Press Ctrl+C to stop.")
        console.print(f"[dim]agent={effective_agent} mode={effective_mode}[/]")
        console.print()

        # Try watchdog first, fall back to polling
        try:
            from watchdog.observers import Observer
            _watch_with_watchdog(root, effective_agent, effective_mode, budget, debounce, state)
        except ImportError:
            console.print("[dim]watchdog not installed — using polling (install watchdog for better performance)[/]")
            _watch_polling(root, effective_agent, effective_mode, budget, debounce, state)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _should_ignore(path: str) -> bool:
    parts = Path(path).parts
    for part in parts:
        if part in _IGNORE_DIRS:
            return True
    name = Path(path).name
    return name in _IGNORE_NAMES


def _run_refresh(root: Path, agent: str, mode: str, budget: int) -> None:
    from agentpack.commands.session import _run_refresh as do_refresh, _file_hash, _now_iso
    result = do_refresh(root, agent, mode, budget)
    if result:
        ts = _ts()
        console.print(
            f"[dim][{ts}][/] [green]refreshed:[/] {result['files']} files, "
            f"{result['tokens']:,} tokens, mode={mode}"
        )
        state = load_session(root)
        if state:
            state.last_refresh_at = _now_iso()
            state.refresh_count += 1
            state.last_task_hash = _file_hash(root / TASK_FILE)
            save_session(root, state)
            log_activity(root, f"watch refresh — {result['files']} files, {result['tokens']:,} tokens")
    else:
        console.print(f"[dim][{_ts()}][/] [red]refresh failed[/]")


def _watch_with_watchdog(
    root: Path,
    agent: str,
    mode: str,
    budget: int,
    debounce: float,
    state,
) -> None:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    _last_refresh = [time.monotonic() - debounce - 1]
    _pending = [False]

    # Run initial refresh
    _run_refresh(root, agent, mode, budget)

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):  # type: ignore[override]
            if event.is_directory:
                return
            path = str(event.src_path)
            if _should_ignore(path):
                return
            # Task file change → show message
            if path.endswith(TASK_FILE):
                console.print(f"[dim][{_ts()}][/] task changed")
            _pending[0] = True

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(0.5)
            if _pending[0]:
                now = time.monotonic()
                if now - _last_refresh[0] >= debounce:
                    _pending[0] = False
                    _last_refresh[0] = now
                    try:
                        _run_refresh(root, agent, mode, budget)
                    except Exception as e:
                        console.print(f"[red]refresh error: {e}[/]")
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watch stopped.[/]")
    observer.join()


def _watch_polling(
    root: Path,
    agent: str,
    mode: str,
    budget: int,
    debounce: float,
    state,
) -> None:
    """Polling fallback: walk repo files and compare mtimes."""
    _POLL_INTERVAL = 1.5

    def _collect_mtimes() -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            if _should_ignore(rel):
                continue
            try:
                mtimes[rel] = p.stat().st_mtime
            except OSError:
                pass
        return mtimes

    prev = _collect_mtimes()
    _run_refresh(root, agent, mode, budget)
    _last_refresh = time.monotonic()

    try:
        while True:
            time.sleep(_POLL_INTERVAL)
            curr = _collect_mtimes()
            changed = {p for p, m in curr.items() if prev.get(p) != m}
            changed |= set(prev) - set(curr)
            if changed:
                task_changed = any(p.endswith(TASK_FILE) for p in changed)
                if task_changed:
                    console.print(f"[dim][{_ts()}][/] task changed")
                now = time.monotonic()
                if now - _last_refresh >= debounce:
                    _last_refresh = now
                    prev = curr
                    try:
                        _run_refresh(root, agent, mode, budget)
                    except Exception as e:
                        console.print(f"[red]refresh error: {e}[/]")
            else:
                prev = curr
    except KeyboardInterrupt:
        console.print("\n[dim]Watch stopped.[/]")
