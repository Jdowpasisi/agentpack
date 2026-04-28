from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box

from agentpack.core.config import Config, load_config, save_config, DEFAULT_CONFIG
from agentpack.core.ignore import load_spec, DEFAULT_AGENTIGNORE
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, save_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.core import git
from agentpack.core.context_pack import select_files, save_pack_metadata, load_pack_metadata
from agentpack.core.models import ContextPack, Receipt
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
from agentpack.summaries.base import build_all_summaries, get_or_build_summary
from agentpack.adapters.claude import ClaudeAdapter
from agentpack.adapters.generic import GenericAdapter

app = typer.Typer(help="AgentPack — token-aware context packing for AI coding agents.")
console = Console()

_ROOT = Path(".")


def _root() -> Path:
    return _ROOT


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Default pack mode (minimal|balanced|deep)."),
    budget: int = typer.Option(0, "--budget", help="Default token budget (0 = keep default 25000)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive prompts, use defaults."),
    share_cache: bool = typer.Option(False, "--share-cache", help="Commit summary cache to git (recommended for teams)."),
) -> None:
    """Initialize AgentPack in the current directory."""
    root = _root()
    agentpack_dir = root / ".agentpack"
    agentpack_dir.mkdir(exist_ok=True)
    (agentpack_dir / "snapshots").mkdir(exist_ok=True)
    (agentpack_dir / "cache").mkdir(exist_ok=True)

    gitignore = agentpack_dir / ".gitignore"
    if not gitignore.exists() or force:
        # With --share-cache, cache/ is committed so teammates skip the summarize step
        cache_line = "" if share_cache else ".agentpack/cache/\n"
        gitignore.write_text(
            f"{cache_line}.agentpack/snapshots/\n.agentpack/context.*\n.agentpack/metrics.jsonl\n"
        )
        console.print("[green]Created[/] .agentpack/.gitignore")
        if share_cache:
            console.print("  [dim]cache/ not gitignored — commit it so teammates skip agentpack summarize[/]")
    else:
        console.print("[dim]Skipped[/] .agentpack/.gitignore (exists)")

    config_path_file = agentpack_dir / "config.toml"
    if not config_path_file.exists() or force:
        cfg = DEFAULT_CONFIG.model_copy(deep=True)

        # Interactive mode selection
        if not yes and mode is None and sys.stdin.isatty():
            console.print("\n[bold]Choose default pack mode:[/]")
            console.print("  [cyan]1[/] minimal  — changed files + configs only (fastest, fewest tokens)")
            console.print("  [cyan]2[/] balanced — + deps, tests, summaries [bold](recommended)[/]")
            console.print("  [cyan]3[/] deep     — + docs, more full files (most context)")
            choice = typer.prompt("Mode", default="2")
            mode_map = {"1": "minimal", "2": "balanced", "3": "deep",
                        "minimal": "minimal", "balanced": "balanced", "deep": "deep"}
            cfg.context.default_mode = mode_map.get(choice.strip(), "balanced")
        elif mode in ("minimal", "balanced", "deep"):
            cfg.context.default_mode = mode

        if budget > 0:
            cfg.context.default_budget = budget

        save_config(cfg, root)
        console.print(f"[green]Created[/] .agentpack/config.toml  [dim](mode: {cfg.context.default_mode}, budget: {cfg.context.default_budget:,})[/]")
    else:
        console.print("[dim]Skipped[/] .agentpack/config.toml (exists)")

    ignore_path = root / ".agentignore"
    if not ignore_path.exists() or force:
        ignore_path.write_text(DEFAULT_AGENTIGNORE)
        console.print("[green]Created[/] .agentignore")
    else:
        console.print("[dim]Skipped[/] .agentignore (exists)")

    console.print("\n[bold green]AgentPack initialized.[/]")
    console.print("Run [bold]agentpack scan[/] to explore your repo.")


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@app.command(name="scan")
def scan_cmd() -> None:
    """Scan the repository and report file statistics."""
    root = _root()
    cfg = load_config(root)
    ignore_spec = load_spec(root / cfg.project.ignore_file)

    console.print("[bold]Scanning repository...[/]")
    files = scan(root, ignore_spec, cfg.context.max_file_tokens)

    total = len(files)
    ignored = sum(1 for f in files if f.ignored or f.binary)
    scanned = total - ignored
    raw_tokens = sum(f.estimated_tokens for f in files)
    after_ignore = sum(f.estimated_tokens for f in files if not f.ignored and not f.binary)

    largest = sorted(
        [f for f in files if not f.ignored and not f.binary],
        key=lambda x: x.estimated_tokens,
        reverse=True,
    )[:10]

    table = Table(title="Repository Scan", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Files discovered", str(total))
    table.add_row("Files ignored / binary", str(ignored))
    table.add_row("Files scanned", str(scanned))
    table.add_row("Raw estimated tokens", f"{raw_tokens:,}")
    table.add_row("Tokens after ignore", f"{after_ignore:,}")
    console.print(table)

    if largest:
        lt = Table(title="Largest Files", show_header=True)
        lt.add_column("File", style="dim")
        lt.add_column("Tokens", justify="right")
        for f in largest:
            lt.add_row(f.path, f"{f.estimated_tokens:,}")
        console.print(lt)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@app.command()
def diff() -> None:
    """Show changes since last snapshot."""
    root = _root()
    cfg = load_config(root)
    ignore_spec = load_spec(root / cfg.project.ignore_file)

    files = scan(root, ignore_spec, cfg.context.max_file_tokens)
    current = build_snapshot(files)
    previous = load_snapshot(root)
    result = diff_snapshots(previous, current)

    table = Table(title="Snapshot Diff", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Added files", str(len(result.added)))
    table.add_row("Modified files", str(len(result.modified)))
    table.add_row("Deleted files", str(len(result.deleted)))
    table.add_row("Unchanged files", str(len(result.unchanged)))
    console.print(table)

    for label, items, style in [
        ("Added", result.added, "green"),
        ("Modified", result.modified, "yellow"),
        ("Deleted", result.deleted, "red"),
    ]:
        if items:
            console.print(f"\n[{style}]{label}:[/]")
            for f in items[:30]:
                console.print(f"  {f}")
            if len(items) > 30:
                console.print(f"  ... and {len(items) - 30} more")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Check if the latest context pack is stale."""
    root = _root()
    cfg = load_config(root)
    ignore_spec = load_spec(root / cfg.project.ignore_file)

    meta = load_pack_metadata(root)
    if not meta:
        console.print("[yellow]No context pack found. Run agentpack pack to generate one.[/]")
        raise typer.Exit(1)

    files = scan(root, ignore_spec, cfg.context.max_file_tokens)
    current = build_snapshot(files)

    if current["root_hash"] == meta.get("snapshot_root_hash"):
        console.print("[green]Context pack is up to date.[/]")
        console.print(f"  Task: {meta.get('task')}")
        console.print(f"  Generated: {meta.get('generated_at')}")
    else:
        console.print("[yellow]Context pack is STALE.[/] Files changed since last pack.")
        console.print(f"  Last generated: {meta.get('generated_at')}")
        console.print("  Run [bold]agentpack pack[/] to refresh.")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@app.command()
def stats() -> None:
    """Show token-saving statistics."""
    root = _root()
    cfg = load_config(root)
    ignore_spec = load_spec(root / cfg.project.ignore_file)

    files = scan(root, ignore_spec, cfg.context.max_file_tokens)
    meta = load_pack_metadata(root)

    raw = sum(f.estimated_tokens for f in files)
    after_ignore = sum(f.estimated_tokens for f in files if not f.ignored and not f.binary)
    packed = meta.get("token_estimate", 0) if meta else 0
    saving = (1 - packed / raw) * 100 if raw > 0 else 0

    ignored_count = sum(1 for f in files if f.ignored or f.binary)
    included_count = 0
    summarized_count = 0

    if meta:
        context_path = root / meta.get("context_path", "")
        if context_path.exists():
            content = context_path.read_text()
            included_count = content.count("Included as: **full**")
            summarized_count = (
                content.count("Included as: **summary**")
                + content.count("Included as: **symbols**")
            )

    # Estimate what manual assembly would cost: changed files full + deps summarized
    # This is the honest comparison — nobody pipes the whole repo into Claude
    full_files = [f for f in files if not f.ignored and not f.binary
                  and f.estimated_tokens <= cfg.context.max_file_tokens]
    manual_estimate = min(after_ignore, sum(f.estimated_tokens for f in full_files[:20]))
    vs_manual = (1 - packed / manual_estimate) * 100 if manual_estimate > 0 else 0

    table = Table(title="Token Stats", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Raw repo tokens", f"{raw:,}")
    table.add_row("After ignore", f"{after_ignore:,}")
    table.add_row("Packed tokens", f"[bold]{packed:,}[/]")
    table.add_row("vs. raw repo", f"[dim]{saving:.1f}% smaller[/]")
    table.add_row("vs. manual assembly (~20 files)", f"[green]{vs_manual:.1f}% smaller[/]")
    table.add_row("Files ignored", f"{ignored_count:,}")
    table.add_row("Files included (full)", f"{included_count:,}")
    table.add_row("Files summarized", f"{summarized_count:,}")
    console.print(table)
    console.print("[dim]'manual assembly' = hand-picking the 20 most relevant full files[/]")


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


@app.command()
def summarize(
    provider: str = typer.Option("offline", "--provider", help="Summary provider (offline|claude)."),
    refresh: bool = typer.Option(False, "--refresh", help="Force rebuild all summaries."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model override (for claude provider)."),
) -> None:
    """Build or refresh summary cache. Default: offline (no API calls)."""
    root = _root()
    cfg = load_config(root)
    ignore_spec = load_spec(root / cfg.project.ignore_file)

    if provider not in ("offline", "claude"):
        console.print("[red]Supported providers: offline, claude[/]")
        raise typer.Exit(1)

    if provider == "claude":
        console.print("[bold]Building LLM summaries via Claude (requires ANTHROPIC_API_KEY)...[/]")
    else:
        console.print("[bold]Building offline summaries...[/]")

    files = scan(root, ignore_spec, cfg.context.max_file_tokens)
    active = [f for f in files if not f.ignored and not f.binary]

    built = 0
    errors = 0
    for fi in active:
        try:
            if provider == "claude" and model:
                # pass model through via a thin wrapper
                from agentpack.summaries import llm as llm_mod
                from agentpack.core import cache as summary_cache
                if fi.hash:
                    cached = summary_cache.load_summary(root, fi.path, fi.hash, provider)
                    if cached and not refresh:
                        built += 1
                        continue
                    summary = llm_mod.summarize(fi.path, fi.abs_path, fi.language, fi.hash or "", provider=provider, model=model)
                    summary_cache.save_summary(root, summary)
            else:
                get_or_build_summary(fi, root, provider)
            built += 1
        except Exception as e:
            console.print(f"[yellow]Warning:[/] {fi.path}: {e}")
            errors += 1

    console.print(f"[green]Done.[/] Built/refreshed {built} summaries.", end="")
    if errors:
        console.print(f" [yellow]{errors} errors.[/]")
    else:
        console.print()


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------


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
    from rich.text import Text

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


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@app.command()
def install(
    agent: str = typer.Option("claude", "--agent", help="Target agent."),
    slash_command: bool = typer.Option(True, "--slash-command/--no-slash-command", help="Install /agentpack slash command."),
    global_install: bool = typer.Option(True, "--global/--local", help="Install globally (~/.claude/commands/) or locally (.claude/commands/)."),
) -> None:
    """Patch CLAUDE.md and install the /agentpack slash command for Claude CLI."""
    root = _root()

    if agent == "claude":
        adapter = ClaudeAdapter()
        action = adapter.patch_claude_md(root)
        console.print(f"[green]CLAUDE.md {action}.[/]")

        if slash_command:
            _install_slash_command(root, global_install)
    else:
        console.print(f"[yellow]No install action defined for agent: {agent}[/]")


def _install_slash_command(root: Path, global_install: bool) -> None:
    import importlib.resources

    commands_dir = (
        Path.home() / ".claude" / "commands" if global_install
        else root / ".claude" / "commands"
    )
    commands_dir.mkdir(parents=True, exist_ok=True)
    dest = commands_dir / "agentpack.md"

    try:
        pkg_files = importlib.resources.files("agentpack") / "data" / "agentpack.md"
        source_text = pkg_files.read_text(encoding="utf-8")
    except Exception:
        source_text = (Path(__file__).parent / "data" / "agentpack.md").read_text()

    dest.write_text(source_text)
    scope = "global" if global_install else "local"
    console.print(f"[green]Slash command installed ({scope}):[/] {dest}")
    console.print("  Use [bold]/agentpack[/] in any Claude CLI session.")


# ---------------------------------------------------------------------------
# Dependency graph builder (Python, JS/TS, Go, Rust, Java/Kotlin)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# global-install
# ---------------------------------------------------------------------------


@app.command(name="global-install")
def global_install_cmd(
    agent: str = typer.Option("claude", "--agent", help="Target agent."),
    pipx: bool = typer.Option(True, "--pipx/--no-pipx", help="Install via pipx for global availability."),
) -> None:
    """Install agentpack globally (pipx) and set up the slash command system-wide."""
    import subprocess as sp

    if pipx:
        console.print("[bold]Installing agentpack globally via pipx...[/]")
        result = sp.run(
            ["pipx", "install", "agentpack", "--force"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print("[green]agentpack installed globally.[/] Available as `agentpack` in any shell.")
        else:
            console.print("[yellow]pipx install failed. Trying pip install --user...[/]")
            result2 = sp.run(
                [sys.executable, "-m", "pip", "install", "--user", "agentpack"],
                capture_output=True, text=True,
            )
            if result2.returncode != 0:
                console.print(f"[red]Install failed:[/] {result2.stderr[:200]}")
                raise typer.Exit(1)
            console.print("[green]Installed via pip --user.[/]")

    # Install slash command globally
    if agent == "claude":
        root = _root()
        _install_slash_command(root, global_install=True)
        console.print("\n[bold green]Global install complete.[/]")
        console.print("  `agentpack` is available in any terminal.")
        console.print("  `/agentpack` is available in any Claude CLI session.")
    else:
        console.print(f"[yellow]No slash command defined for agent: {agent}[/]")


# ---------------------------------------------------------------------------
# monitor
# ---------------------------------------------------------------------------


@app.command()
def monitor(
    last: int = typer.Option(20, "--last", "-n", help="Show last N pack runs."),
    clear: bool = typer.Option(False, "--clear", help="Delete metrics log."),
) -> None:
    """Show pack performance metrics across runs."""
    root = _root()
    metrics_path = root / ".agentpack" / "metrics.jsonl"

    if clear:
        if metrics_path.exists():
            metrics_path.unlink()
            console.print("[green]Metrics log cleared.[/]")
        else:
            console.print("[dim]No metrics log found.[/]")
        return

    if not metrics_path.exists():
        console.print("[yellow]No metrics recorded yet. Run agentpack pack first.[/]")
        raise typer.Exit(1)

    records = []
    for line in metrics_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not records:
        console.print("[yellow]Metrics log is empty.[/]")
        raise typer.Exit(1)

    recent = records[-last:]

    # Summary stats
    savings = [r["saving_pct"] for r in recent]
    totals = [r["total_s"] for r in recent]
    avg_saving = sum(savings) / len(savings)
    avg_total = sum(totals) / len(totals)
    best_saving = max(savings)

    summary_table = Table(title="Performance Summary", show_header=True, box=box.SIMPLE)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", justify="right")
    summary_table.add_row("Runs recorded", str(len(records)))
    summary_table.add_row("Shown", str(len(recent)))
    summary_table.add_row("Avg saving", f"[green]{avg_saving:.1f}%[/]")
    summary_table.add_row("Best saving", f"[green]{best_saving:.1f}%[/]")
    summary_table.add_row("Avg pack time", f"{avg_total:.2f}s")
    console.print(summary_table)

    # Per-run table
    run_table = Table(title=f"Last {len(recent)} Runs", show_header=True, box=box.SIMPLE)
    run_table.add_column("When", style="dim", max_width=20)
    run_table.add_column("Task", max_width=35)
    run_table.add_column("Mode", width=9)
    run_table.add_column("Saving", justify="right")
    run_table.add_column("Packed", justify="right")
    run_table.add_column("Total", justify="right")
    run_table.add_column("scan", justify="right", style="dim")
    run_table.add_column("sum", justify="right", style="dim")
    run_table.add_column("rank", justify="right", style="dim")

    for r in recent:
        ts = r.get("ts", "")[:16].replace("T", " ")
        phases = r.get("phases", {})
        run_table.add_row(
            ts,
            r.get("task", "")[:35],
            r.get("mode", ""),
            f"[green]{r['saving_pct']:.1f}%[/]",
            f"{r['packed_tokens']:,}",
            f"{r['total_s']:.2f}s",
            f"{phases.get('scan', 0):.2f}s",
            f"{phases.get('summarize', 0):.2f}s",
            f"{phases.get('rank', 0):.2f}s",
        )

    console.print(run_table)

    # Phase breakdown averaged
    phase_keys = ["scan", "summarize", "deps", "changes", "rank", "select", "render"]
    phase_table = Table(title="Avg Phase Times", show_header=True, box=box.SIMPLE)
    phase_table.add_column("Phase", style="cyan")
    phase_table.add_column("Avg (s)", justify="right")
    phase_table.add_column("Max (s)", justify="right")
    for pk in phase_keys:
        vals = [r.get("phases", {}).get(pk, 0) for r in recent]
        if any(v > 0 for v in vals):
            phase_table.add_row(pk, f"{sum(vals)/len(vals):.3f}", f"{max(vals):.3f}")
    console.print(phase_table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
