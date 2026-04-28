from __future__ import annotations

from typing import Optional

import typer

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.core import git
from agentpack.core.context_pack import select_files
from agentpack.analysis.ranking import score_files, extract_keywords, enrich_keywords_from_files
from agentpack.analysis.tests import find_related_tests
from agentpack.summaries.base import build_all_summaries
from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task, _build_dep_graph


def register(app: typer.Typer) -> None:
    @app.command()
    def explain(
        task: str = typer.Option("auto", "--task", help="Task description, or 'auto' to infer from git."),
        mode: str = typer.Option("balanced", "--mode", help="Budget mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = use config default)."),
        since: Optional[str] = typer.Option(None, "--since", help="Git ref to compare against (e.g. HEAD~1, main)."),
        summary_provider: str = typer.Option("offline", "--summary-provider", help="Summary provider (offline|claude)."),
    ) -> None:
        """Explain which files would be selected and why, without writing a context file."""
        if mode not in ("minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
            raise typer.Exit(1)

        resolved_task = _resolve_task(task)
        _do_explain(
            task=resolved_task,
            mode=mode,
            budget=budget,
            since=since,
            summary_provider=summary_provider,
        )


def _do_explain(
    task: str,
    mode: str,
    budget: int,
    since: str | None,
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

    # Build a score lookup from the scored list
    score_map: dict[str, tuple[float, list[str]]] = {
        fi.path: (score, reasons) for fi, score, reasons in scored
    }

    # Collect excluded files (budget exhausted or score too low) for display
    selected_paths = {sf.path for sf in selected}
    excluded_receipts = [
        r for r in receipts
        if r.action == "excluded" and r.reason not in ("ignored or binary",)
        and r.path in score_map
    ]
    # Sort excluded by score descending
    excluded_receipts.sort(key=lambda r: -score_map[r.path][0])

    # Find files near budget cutoff: excluded due to budget exhausted with a deep-mode budget
    deep_budget = effective_budget * 2
    _, deep_receipts = select_files(
        files=files,
        scored=scored,
        changed_paths=all_changed,
        summaries=summaries,
        mode=mode,  # type: ignore[arg-type]
        budget=deep_budget,
        max_file_tokens=cfg.context.max_file_tokens,
        keywords=keywords,
    )
    deep_selected_paths = {
        r.path for r in deep_receipts if r.action in ("included", "summarized")
    }
    near_cutoff_paths = deep_selected_paths - selected_paths

    # Print header
    console.print(f"\n[bold]Task:[/] [cyan]{task}[/]  [dim]mode={mode}  budget={effective_budget:,}[/]\n")

    # Top selected files
    console.print("[bold]Top selected files (ranked):[/]")
    for i, sf in enumerate(selected, 1):
        score_val, reasons = score_map.get(sf.path, (sf.score, sf.reasons))
        reason_str = reasons[0] if reasons else ""
        console.print(
            f"  [bold]{i}.[/] {sf.path:<50} "
            f"[dim]score={score_val:.0f}[/]  "
            f"[[{'green' if sf.include_mode == 'full' else 'yellow' if sf.include_mode == 'symbols' else 'dim'}]{sf.include_mode}[/]]  "
            f"[dim]{reason_str}[/]"
        )

    # Near-cutoff files
    if near_cutoff_paths:
        console.print(f"\n[bold]Files near budget cutoff[/] [dim](would appear with larger budget):[/]")
        near_sorted = sorted(
            near_cutoff_paths,
            key=lambda p: -score_map.get(p, (0, []))[0],
        )
        for i, path in enumerate(near_sorted[:5], len(selected) + 1):
            score_val, reasons = score_map.get(path, (0, []))
            reason_str = reasons[0] if reasons else ""
            console.print(
                f"  [dim]{i}.[/] {path:<50} "
                f"[dim]score={score_val:.0f}   {reason_str}[/]"
            )

    # Top excluded files
    if excluded_receipts:
        console.print(f"\n[bold]Excluded[/] [dim](top 5 by score):[/]")
        for r in excluded_receipts[:5]:
            score_val, _ = score_map.get(r.path, (0, []))
            console.print(
                f"  [dim]-[/] {r.path:<50} "
                f"[dim]score={score_val:.0f}   {r.reason}[/]"
            )

    console.print()
