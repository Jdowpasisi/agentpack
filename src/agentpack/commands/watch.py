from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import typer

from agentpack.commands._shared import console, _root, run_refresh, _file_hash, _now_iso
from agentpack.session.state import TASK_FILE, load_session, save_session, log_activity


_IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", ".next",
    "__pycache__", ".yarn", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".tox", ".eggs", "*.egg-info",
    # IDE state dirs — written constantly by editors, never user source
    ".vscode", ".idea", ".fleet",
}
_IGNORE_NAMES = {"context.md", "context.compact.md"}
_IGNORE_SUFFIXES = {".tsbuildinfo"}  # TypeScript incremental build artifacts
# Ignore all .agentpack/ generated files; task.md is the sole exception (user-edited, triggers refresh)

# Adapter output paths written outside .agentpack/ (e.g. antigravity writes .agent/skills/agentpack/SKILL.md).
# Populated at runtime from run_refresh() return value so new adapters are covered automatically.
_WRITTEN_PATHS: set[str] = set()

_MAX_POLL_FILES = 50_000


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

        # Auto-resume: if session exists but inactive, reactivate without requiring `session start`
        if state is not None and not state.active:
            state.active = True
            save_session(root, state)
            console.print("[dim]Resumed session.[/]")
        elif state is None:
            console.print("[yellow]No session found — watching in stateless mode.[/]")
            console.print("[dim]Run 'agentpack session start' to persist agent/mode preferences.[/]")

        effective_agent = agent or (state.agent if state else "generic")
        effective_mode = mode or (state.mode if state else "balanced")

        console.print()
        console.print("[bold]AgentPack watch active.[/]")
        console.print("Press Ctrl+C to stop.")
        console.print(f"[dim]agent={effective_agent} mode={effective_mode}[/]")
        console.print()

        # Try watchdog first, fall back to polling
        try:
            import importlib.util
            if importlib.util.find_spec("watchdog") is None:
                raise ImportError("watchdog not installed")
            _watch_with_watchdog(root, effective_agent, effective_mode, budget, debounce, state)
        except ImportError:
            console.print("[dim]watchdog unavailable — using polling[/]")
            _watch_polling(root, effective_agent, effective_mode, budget, debounce, state)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _should_ignore(path: str) -> bool:
    parts = Path(path).parts
    for part in parts:
        if part in _IGNORE_DIRS:
            return True
    name = Path(path).name
    if name in _IGNORE_NAMES:
        return True
    if any(name.endswith(suf) for suf in _IGNORE_SUFFIXES):
        return True
    norm = path.replace("\\", "/")
    # Ignore everything under .agentpack/ except task.md
    if norm.startswith(".agentpack/") and norm != TASK_FILE:
        return True
    # Ignore adapter output files written outside .agentpack/ during refresh
    if norm in _WRITTEN_PATHS:
        return True
    return False


def _run_refresh(root: Path, agent: str, mode: str, budget: int) -> None:
    try:
        result = run_refresh(root, agent, mode, budget)
    except Exception as e:
        console.print(f"[dim][{_ts()}][/] [red]refresh error: {e}[/]")
        return
    if result:
        # Register adapter output path so _should_ignore suppresses the write event
        out_path = result.get("out_path")
        if out_path is not None:
            try:
                _WRITTEN_PATHS.add(str(Path(out_path).relative_to(root)).replace("\\", "/"))
            except ValueError:
                pass
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
            state.last_resolved_agent = agent
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
        def _handle(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            try:
                path = str(Path(event.src_path).relative_to(root))
            except ValueError:
                return
            if _should_ignore(path):
                return
            if path.endswith(TASK_FILE):
                console.print(f"[dim][{_ts()}][/] task changed")
            _pending[0] = True

        # Only react to mutations — not reads (avoids inotify IN_ACCESS loop on Linux)
        on_created = _handle
        on_modified = _handle
        on_deleted = _handle

        def on_moved(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            # Check both src (rename from) and dest (rename to)
            for raw in (event.src_path, event.dest_path):
                try:
                    path = str(Path(raw).relative_to(root))
                except ValueError:
                    continue
                if not _should_ignore(path):
                    _pending[0] = True
                    return

    observer = Observer()
    try:
        observer.schedule(Handler(), str(root), recursive=True)
        observer.start()
    except Exception as e:
        console.print(f"[red]Failed to start file watcher: {e}[/]")
        console.print("[dim]Falling back to polling.[/]")
        _watch_polling(root, agent, mode, budget, debounce, state)
        return

    try:
        while True:
            time.sleep(0.5)
            if not observer.is_alive():
                console.print(f"[dim][{_ts()}][/] [yellow]watcher thread died — restarting...[/]")
                try:
                    observer.stop()
                except Exception:
                    pass
                _watch_polling(root, agent, mode, budget, debounce, state)
                return
            current_state = load_session(root)
            if current_state is not None and not current_state.active:
                console.print("\n[dim]Session stopped — watch exiting.[/]")
                observer.stop()
                break
            if _pending[0]:
                now = time.monotonic()
                if now - _last_refresh[0] >= debounce:
                    _pending[0] = False
                    _last_refresh[0] = now
                    _run_refresh(root, agent, mode, budget)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watch stopped.[/]")
    finally:
        observer.join(timeout=3)


def _collect_mtimes(root: Path) -> dict[str, float]:
    """Walk repo files without following symlinks; cap at _MAX_POLL_FILES."""
    mtimes: dict[str, float] = {}
    try:
        for entry in _walk_no_symlinks(root):
            rel = str(Path(entry).relative_to(root))
            if _should_ignore(rel):
                continue
            try:
                mtimes[rel] = os.stat(entry).st_mtime
            except OSError:
                pass
            if len(mtimes) >= _MAX_POLL_FILES:
                break
    except OSError:
        pass
    return mtimes


def _walk_no_symlinks(root: Path):
    """os.walk without following symlinks — avoids infinite loops in symlink forests."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=lambda e: None):
        # Prune ignored dirs in-place so os.walk won't descend into them
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORE_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            if not os.path.islink(fpath):
                yield fpath


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

    prev = _collect_mtimes(root)
    _run_refresh(root, agent, mode, budget)
    _last_refresh = time.monotonic()

    try:
        while True:
            time.sleep(_POLL_INTERVAL)
            current_state = load_session(root)
            if current_state is not None and not current_state.active:
                console.print("\n[dim]Session stopped — watch exiting.[/]")
                break
            curr = _collect_mtimes(root)
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
                    _run_refresh(root, agent, mode, budget)
            else:
                prev = curr
    except KeyboardInterrupt:
        console.print("\n[dim]Watch stopped.[/]")
