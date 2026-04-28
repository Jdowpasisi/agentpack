from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich import box

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, save_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.core import git
from agentpack.core.context_pack import select_files, save_pack_metadata
from agentpack.core.models import ContextPack
from agentpack.core.token_estimator import estimate_tokens
from agentpack.analysis.ranking import score_files, extract_keywords, enrich_keywords_from_files
from agentpack.analysis.tests import find_related_tests
from agentpack.analysis.python_imports import extract_imports as py_imports
from agentpack.analysis.python_imports import resolve_relative_import as py_resolve
from agentpack.analysis.js_ts_imports import extract_imports as js_imports
from agentpack.analysis.js_ts_imports import resolve_relative_import as js_resolve
from agentpack.analysis.go_imports import extract_imports as go_imports
from agentpack.analysis.rust_imports import extract_imports as rust_imports
from agentpack.analysis.java_imports import extract_imports as java_imports
from agentpack.summaries.base import build_all_summaries
from agentpack.adapters.claude import ClaudeAdapter
from agentpack.adapters.generic import GenericAdapter
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def pack(
        agent: str = typer.Option("claude", "--agent", help="Target agent (claude|generic)."),
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

        _do_pack(
            agent=agent, task=resolved_task, mode=mode, budget=budget,
            since=since, print_output=print_output,
            refresh=refresh, summary_provider=summary_provider,
        )


def _resolve_task(task: str) -> str:
    """Resolve 'auto' to an inferred task string from git context."""
    if task != "auto":
        return task
    inferred = git.infer_task_from_git(_root())
    console.print(f"[dim]Auto task: {inferred}[/]")
    return inferred


def _sf_tokens(sf) -> int:  # type: ignore[no-untyped-def]
    """Accurate token count for a SelectedFile regardless of include mode."""
    if sf.content:
        return estimate_tokens(sf.content)
    parts: list[str] = []
    if sf.summary:
        parts.append(sf.summary)
    for sym in sf.symbols:
        if sym.signature:
            parts.append(sym.signature)
    return estimate_tokens("\n".join(parts)) if parts else 50


def _do_pack(
    agent: str,
    task: str,
    mode: str,
    budget: int,
    since: str | None,
    print_output: bool,
    refresh: bool,
    summary_provider: str,
) -> None:
    root = _root()
    cfg = load_config(root)
    effective_budget = budget if budget > 0 else cfg.context.default_budget
    ignore_spec = load_spec(root / cfg.project.ignore_file)
    phase_times: dict[str, float] = {}

    t0 = time.perf_counter()
    with console.status("[bold]Scanning repository..."):
        files = scan(root, ignore_spec, cfg.context.max_file_tokens)
    phase_times["scan"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with console.status("[bold]Building summaries..."):
        summaries_objs = build_all_summaries(files, root, summary_provider)
        summaries = {p: s.model_dump() for p, s in summaries_objs.items()}
    phase_times["summarize"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with console.status("[bold]Building dependency graph..."):
        dep_graph = _build_dep_graph(files, root)
    phase_times["deps"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with console.status("[bold]Detecting changes..."):
        current_snap = build_snapshot(files)
        previous_snap = load_snapshot(root)
        snap_diff = diff_snapshots(previous_snap, current_snap)
        changed_from_snap: set[str] = set(snap_diff.added + snap_diff.modified)

        git_changed: set[str] = set()
        git_staged: set[str] = set()
        recently_modified: list[str] = []

        if git.is_git_repo(root):
            if since:
                git_changed = git.changed_files_since(root, since)
            else:
                git_changed = git.changed_files(root)
            git_staged = git_changed
            recently_modified = git.recently_modified_files(root)

        all_changed = changed_from_snap | git_changed
    phase_times["changes"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with console.status("[bold]Ranking files..."):
        keywords = extract_keywords(task)
        keywords = enrich_keywords_from_files(keywords, all_changed, files)
        all_paths = {f.path for f in files}

        for fi in files:
            graph_entry = dep_graph.get(fi.path, {})
            tests = find_related_tests(fi.path, all_paths)
            graph_entry["tests"] = tests
            dep_graph[fi.path] = graph_entry

        scored = score_files(
            files,
            changed_paths=all_changed,
            staged_paths=git_staged,
            recently_modified=recently_modified,
            dep_graph=dep_graph,
            keywords=keywords,
            include_tests=cfg.context.include_tests,
            include_configs=cfg.context.include_configs,
            weights=cfg.scoring,
        )
    phase_times["rank"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    with console.status("[bold]Selecting files within budget..."):
        selected, receipts = select_files(
            files=files,
            scored=scored,
            changed_paths=all_changed,
            summaries=summaries,
            mode=mode,  # type: ignore[arg-type]
            budget=effective_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=keywords,
        )
    phase_times["select"] = time.perf_counter() - t0

    raw_tokens = sum(f.estimated_tokens for f in files)
    after_ignore = sum(f.estimated_tokens for f in files if not f.ignored and not f.binary)
    packed_tokens = sum(_sf_tokens(sf) for sf in selected)
    saving_pct = (1 - packed_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0.0

    pack_obj = ContextPack(
        task=task,
        agent=agent,
        mode=mode,  # type: ignore[arg-type]
        budget=effective_budget,
        token_estimate=packed_tokens,
        raw_repo_tokens=raw_tokens,
        after_ignore_tokens=after_ignore,
        estimated_savings_percent=saving_pct,
        changed_files=sorted(all_changed),
        selected_files=selected,
        receipts=receipts if cfg.context.include_receipts else [],
        stale=False,
    )

    if agent == "claude":
        adapter = ClaudeAdapter(cfg.agents.claude.output)
    else:
        adapter = GenericAdapter(cfg.agents.generic.output)

    t0 = time.perf_counter()
    out_path = adapter.write(pack_obj, root)
    phase_times["render"] = time.perf_counter() - t0

    save_snapshot(current_snap, root)
    save_pack_metadata(
        root,
        context_path=str(out_path.relative_to(root)),
        snapshot_root_hash=current_snap["root_hash"],
        task=task,
        agent=agent,
        mode=mode,
        budget=effective_budget,
        token_estimate=packed_tokens,
    )

    _print_pack_summary(
        out_path=out_path,
        selected=selected,
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        saving_pct=saving_pct,
        changed_files=sorted(all_changed),
        task=task,
        since=since,
    )

    if print_output:
        print(out_path.read_text())

    _record_metrics(root, task=task, mode=mode, phase_times=phase_times,
                    packed_tokens=packed_tokens, raw_tokens=raw_tokens,
                    saving_pct=saving_pct, selected_count=len(selected),
                    changed_count=len(all_changed))


def _record_metrics(root: Path, *, task: str, mode: str, phase_times: dict[str, float],
                    packed_tokens: int, raw_tokens: int, saving_pct: float,
                    selected_count: int, changed_count: int) -> None:
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "mode": mode,
        "packed_tokens": packed_tokens,
        "raw_tokens": raw_tokens,
        "saving_pct": round(saving_pct, 1),
        "selected_files": selected_count,
        "changed_files": changed_count,
        "phases": {k: round(v, 3) for k, v in phase_times.items()},
        "total_s": round(sum(phase_times.values()), 3),
    }
    try:
        with metrics_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _print_pack_summary(
    out_path: Path,
    selected: list,
    packed_tokens: int,
    raw_tokens: int,
    saving_pct: float,
    changed_files: list[str],
    task: str,
    since: str | None,
) -> None:
    from rich.text import Text  # noqa: F401

    # ── Stats row ──────────────────────────────────────────────────────────
    stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats.add_column(style="dim")
    stats.add_column(justify="right", style="bold")
    stats.add_row("packed tokens", f"{packed_tokens:,}")
    stats.add_row("raw tokens", f"{raw_tokens:,}")
    stats.add_row("saving", f"[green]{saving_pct:.1f}%[/]")
    if since:
        stats.add_row("changes since", since)

    # ── Selected files table ───────────────────────────────────────────────
    MODE_STYLE = {"full": "green", "symbols": "yellow", "summary": "dim"}
    files_tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    files_tbl.add_column("file", style="dim", no_wrap=False, max_width=55)
    files_tbl.add_column("mode", justify="center", width=8)
    files_tbl.add_column("why", style="dim", max_width=30)

    for sf in selected[:20]:
        style = MODE_STYLE.get(sf.include_mode, "")
        changed_marker = " [red]●[/]" if sf.path in changed_files else ""
        files_tbl.add_row(
            f"{sf.path}{changed_marker}",
            f"[{style}]{sf.include_mode}[/]",
            sf.reasons[0] if sf.reasons else "",
        )
    if len(selected) > 20:
        files_tbl.add_row(f"[dim]... {len(selected) - 20} more[/]", "", "")

    # ── Changed files list ─────────────────────────────────────────────────
    if changed_files:
        changed_lines = "\n".join(f"  [red]●[/] {f}" for f in changed_files[:10])
        if len(changed_files) > 10:
            changed_lines += f"\n  [dim]... {len(changed_files) - 10} more[/]"
    else:
        changed_lines = "  [dim]none detected[/]"

    # ── Render ─────────────────────────────────────────────────────────────
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
    cfg = load_config(root)

    console.print(f"[bold]Watch mode active.[/] Repacking on file changes... (Ctrl+C to stop)")
    console.print(f"  Task: {task}")

    # Run once immediately
    _do_pack(agent=agent, task=task, mode=mode, budget=budget,
             since=since, print_output=False, refresh=False,
             summary_provider=summary_provider)

    _last_pack = [time.time()]
    _DEBOUNCE = 2.0  # seconds

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):  # type: ignore[override]
            if event.is_directory:
                return
            path = str(event.src_path)
            # Skip .agentpack/ changes (our own output)
            if ".agentpack" in path:
                return
            now = time.time()
            if now - _last_pack[0] < _DEBOUNCE:
                return
            _last_pack[0] = now
            console.print(f"\n[dim]Change detected: {event.src_path}[/]")
            try:
                _do_pack(agent=agent, task=task, mode=mode, budget=budget,
                         since=since, print_output=False, refresh=False,
                         summary_provider=summary_provider)
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


def _build_dep_graph(files: list, root: Path) -> dict[str, dict]:
    graph: dict[str, dict] = {
        fi.path: {"imports": [], "imported_by": [], "tests": []} for fi in files
    }
    path_set = {fi.path for fi in files}

    for fi in files:
        if fi.ignored or fi.binary:
            continue

        raw_imports: list[str] = []
        lang = fi.language

        if lang == "python":
            raw_imports = py_imports(fi.abs_path)
        elif lang in ("javascript", "typescript"):
            raw_imports = js_imports(fi.abs_path)
        elif lang == "go":
            raw_imports = go_imports(fi.abs_path)
        elif lang == "rust":
            raw_imports = rust_imports(fi.abs_path)
        elif lang in ("java", "kotlin"):
            raw_imports = java_imports(fi.abs_path)

        resolved: list[str] = []
        for imp in raw_imports:
            if imp.startswith("."):
                if lang == "python":
                    r = py_resolve(fi.path, imp, root)
                elif lang in ("javascript", "typescript"):
                    r = js_resolve(fi.path, imp, root)
                else:
                    r = None
                if r and r in path_set:
                    resolved.append(r)
            else:
                resolved.append(imp)

        graph[fi.path]["imports"] = resolved
        for dep in resolved:
            if dep in graph:
                graph[dep]["imported_by"].append(fi.path)

    return graph
