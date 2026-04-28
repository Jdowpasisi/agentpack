from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from agentpack.core.config import Config, load_config, save_config, DEFAULT_CONFIG
from agentpack.core.ignore import load_spec, DEFAULT_AGENTIGNORE
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, save_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.core import git
from agentpack.core.context_pack import select_files, save_pack_metadata, load_pack_metadata
from agentpack.core.models import ContextPack, Receipt
from agentpack.core.token_estimator import estimate_tokens
from agentpack.analysis.ranking import score_files, extract_keywords
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
) -> None:
    """Initialize AgentPack in the current directory."""
    root = _root()
    agentpack_dir = root / ".agentpack"
    agentpack_dir.mkdir(exist_ok=True)
    (agentpack_dir / "snapshots").mkdir(exist_ok=True)
    (agentpack_dir / "cache").mkdir(exist_ok=True)

    gitignore = agentpack_dir / ".gitignore"
    if not gitignore.exists() or force:
        gitignore.write_text(
            ".agentpack/cache/\n.agentpack/snapshots/\n.agentpack/context.*\n"
        )
        console.print("[green]Created[/] .agentpack/.gitignore")
    else:
        console.print("[dim]Skipped[/] .agentpack/.gitignore (exists)")

    config_path = agentpack_dir / "config.toml"
    if not config_path.exists() or force:
        save_config(DEFAULT_CONFIG, root)
        console.print("[green]Created[/] .agentpack/config.toml")
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

    table = Table(title="Token Stats", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Raw repo tokens", f"{raw:,}")
    table.add_row("After ignore", f"{after_ignore:,}")
    table.add_row("Packed tokens", f"{packed:,}")
    table.add_row("Estimated saving", f"{saving:.1f}%")
    table.add_row("Files ignored", f"{ignored_count:,}")
    table.add_row("Files included (full)", f"{included_count:,}")
    table.add_row("Files summarized", f"{summarized_count:,}")
    console.print(table)


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
    task: str = typer.Option(..., "--task", help="Task description."),
    mode: str = typer.Option("balanced", "--mode", help="Budget mode (minimal|balanced|deep)."),
    budget: int = typer.Option(0, "--budget", help="Token budget (0 = use config default)."),
    since: Optional[str] = typer.Option(None, "--since", help="Git ref to compare against (e.g. HEAD~1, main)."),
    print_output: bool = typer.Option(False, "--print", help="Print context to stdout."),
    refresh: bool = typer.Option(False, "--refresh", help="Rebuild summaries before packing."),
    summary_provider: str = typer.Option("offline", "--summary-provider", help="Summary provider (offline|claude)."),
    watch: bool = typer.Option(False, "--watch", help="Watch for file changes and re-pack automatically."),
) -> None:
    """Generate a context pack for an AI coding agent."""
    if mode not in ("minimal", "balanced", "deep"):
        console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
        raise typer.Exit(1)

    if watch:
        _pack_watch(agent=agent, task=task, mode=mode, budget=budget,
                    since=since, summary_provider=summary_provider)
        return

    _do_pack(
        agent=agent, task=task, mode=mode, budget=budget,
        since=since, print_output=print_output,
        refresh=refresh, summary_provider=summary_provider,
    )


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

    with console.status("[bold]Scanning repository..."):
        files = scan(root, ignore_spec, cfg.context.max_file_tokens)

    with console.status("[bold]Building summaries..."):
        summaries_objs = build_all_summaries(files, root, summary_provider)
        summaries = {p: s.model_dump() for p, s in summaries_objs.items()}

    with console.status("[bold]Building dependency graph..."):
        dep_graph = _build_dep_graph(files, root)

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

    with console.status("[bold]Ranking files..."):
        keywords = extract_keywords(task)
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

    raw_tokens = sum(f.estimated_tokens for f in files)
    after_ignore = sum(f.estimated_tokens for f in files if not f.ignored and not f.binary)
    packed_tokens = sum(
        estimate_tokens(sf.content) if sf.content else 200
        for sf in selected
    )
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

    out_path = adapter.write(pack_obj, root)

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

    console.print(f"\n[bold green]Context pack generated:[/] {out_path}")
    console.print(f"  Files selected:   {len(selected)}")
    console.print(f"  Packed tokens:    {packed_tokens:,}")
    console.print(f"  Raw tokens:       {raw_tokens:,}")
    console.print(f"  Estimated saving: {saving_pct:.1f}%")
    if since:
        console.print(f"  Changes since:    {since}")

    if print_output:
        print(out_path.read_text())


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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
