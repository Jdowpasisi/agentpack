from __future__ import annotations

import re
from typing import Optional

import typer

from agentpack.application.pack_service import PackPlanner, PackRequest
from agentpack.core.context_pack import select_files
from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task
from agentpack.core.config import load_config, ScoringWeights


def _resolve_signal_weight(reason: str, weights: ScoringWeights) -> float:
    """Map a reason string to its numeric weight value."""
    reason_lower = reason.lower()
    if reason_lower == "modified":
        return weights.modified
    if reason_lower == "staged":
        return weights.staged
    if reason_lower == "filename keyword match":
        return weights.filename_keyword
    if reason_lower == "symbol keyword match":
        return weights.symbol_keyword
    m = re.match(r"content keyword match \((\d+)\)", reason_lower)
    if m:
        n = int(m.group(1))
        return min(n * weights.content_keyword_per_hit, weights.content_keyword_max)
    if reason_lower == "direct dependency of changed file":
        return weights.direct_dep
    if reason_lower == "reverse dependency":
        return weights.reverse_dep
    if reason_lower == "has related tests":
        return weights.related_test
    if reason_lower == "config file":
        return weights.config_file
    if reason_lower == "recently modified":
        return weights.recently_modified
    if reason_lower in ("large/unrelated file", "large unrelated file"):
        return weights.large_unrelated_penalty
    return 0.0


def _print_file_detail(
    file_path: str,
    plan: object,
    weights: ScoringWeights,
    near_cutoff_paths: set[str],
) -> None:
    """Print per-file score breakdown."""
    score_map: dict[str, tuple[float, list[str]]] = {
        fi.path: (score, reasons) for fi, score, reasons in plan.scored  # type: ignore[attr-defined]
    }

    if file_path not in score_map:
        console.print(f"[red]File not found in scoring data: {file_path}[/]")
        raise typer.Exit(1)

    score_val, reasons = score_map[file_path]

    # Find in selected
    selected_file = None
    for sf in plan.selected:  # type: ignore[attr-defined]
        if sf.path == file_path:
            selected_file = sf
            break

    is_selected = selected_file is not None
    would_appear = file_path in near_cutoff_paths

    # Token count from selected file, fall back to FileInfo scan estimate
    token_count = 0
    if selected_file is not None:
        from agentpack.application.pack_service import _sf_tokens
        token_count = _sf_tokens(selected_file)
    else:
        for fi in plan.scan_result.packable:  # type: ignore[attr-defined]
            if fi.path == file_path:
                token_count = fi.estimated_tokens
                break

    include_mode = selected_file.include_mode if selected_file else "—"

    # Symbols from plan.summaries
    summary_data = plan.summaries.get(file_path, {})  # type: ignore[attr-defined]
    raw_symbols = summary_data.get("symbols", []) if isinstance(summary_data, dict) else []
    symbol_names = [s["name"] if isinstance(s, dict) else s.name for s in raw_symbols]

    console.print()
    console.print(f"[bold]{file_path}[/]")
    console.print(f"  selected:  {'[green]yes[/]' if is_selected else '[yellow]no[/]'}")
    if not is_selected:
        console.print(f"  would appear with larger budget:  {'[cyan]yes[/]' if would_appear else 'no'}")
    console.print(f"  score:     [bold]{score_val:.0f}[/]")
    console.print(f"  include:   {include_mode}")
    console.print(f"  tokens:    {token_count:,}")
    console.print()
    console.print("  [bold]signals:[/]")
    if reasons:
        for reason in reasons:
            weight = _resolve_signal_weight(reason, weights)
            sign = "+" if weight >= 0 else ""
            color = "green" if weight > 0 else "red" if weight < 0 else "dim"
            console.print(f"    [{color}]{sign}{weight:.0f}[/]  {reason}")
    else:
        console.print("    [dim](none)[/]")
    if symbol_names:
        console.print()
        console.print(f"  [bold]symbols:[/] {', '.join(symbol_names)}")
    console.print()


def register(app: typer.Typer) -> None:
    @app.command()
    def explain(
        task: str = typer.Option("auto", "--task", help="Task description, or 'auto' to infer from git."),
        mode: str = typer.Option("balanced", "--mode", help="Budget mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = use config default)."),
        since: Optional[str] = typer.Option(None, "--since", help="Git ref to compare against (e.g. HEAD~1, main)."),
        file: Optional[str] = typer.Option(None, "--file", help="Show detailed score breakdown for a specific file."),
        omitted: bool = typer.Option(False, "--omitted", is_flag=True, help="Show top-10 excluded files and why."),
    ) -> None:
        """Explain which files would be selected and why, without writing a context file."""
        if mode not in ("minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
            raise typer.Exit(1)

        root = _root()
        resolved_task = _resolve_task(task)

        request = PackRequest(
            root=root,
            agent="generic",
            task=resolved_task,
            mode=mode,
            budget=budget,
            since=since,
            refresh=False,
        )

        with console.status("[bold]Planning..."):
            plan = PackPlanner().plan(request)

        selected = plan.selected
        receipts = plan.receipts
        score_map: dict[str, tuple[float, list[str]]] = {
            fi.path: (score, reasons) for fi, score, reasons in plan.scored
        }

        selected_paths = {sf.path for sf in selected}
        excluded_receipts = [
            r for r in receipts
            if r.action == "excluded" and r.reason not in ("ignored or binary",)
            and r.path in score_map
        ]
        excluded_receipts.sort(key=lambda r: -score_map[r.path][0])

        cfg = load_config(root)
        deep_budget = plan.budget * 2
        _, deep_receipts = select_files(
            files=plan.scan_result.packable,
            scored=plan.scored,
            changed_paths=plan.all_changed,
            summaries=plan.summaries,
            mode=mode,  # type: ignore[arg-type]
            budget=deep_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=plan.keywords,
        )
        deep_selected_paths = {
            r.path for r in deep_receipts if r.action in ("included", "summarized")
        }
        near_cutoff_paths = deep_selected_paths - selected_paths

        # --file: per-file detail view
        if file is not None:
            console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]")
            _print_file_detail(file, plan, cfg.scoring, near_cutoff_paths)
            return

        # --omitted: dedicated excluded file view
        if omitted:
            console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")
            console.print("[bold]Top excluded files (by score):[/]")
            if not excluded_receipts:
                console.print("  [dim](none)[/]")
            else:
                for r in excluded_receipts[:10]:
                    score_val, reasons = score_map.get(r.path, (0, []))
                    reason_str = reasons[0] if reasons else ""
                    console.print(
                        f"  [dim]-[/] {r.path:<50} "
                        f"[dim]score={score_val:.0f}   {r.reason}[/]"
                        + (f"  [dim]({reason_str})[/]" if reason_str and reason_str != r.reason else "")
                    )
            console.print()
            return

        console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")

        console.print("[bold]Top selected files (ranked):[/]")
        for i, sf in enumerate(selected, 1):
            score_val, reasons = score_map.get(sf.path, (sf.score, sf.reasons))
            reason_str = ", ".join(reasons) if reasons else ""
            mode_color = "green" if sf.include_mode == "full" else "yellow" if sf.include_mode == "symbols" else "dim"
            console.print(
                f"  [bold]{i}.[/] {sf.path:<50} "
                f"[dim]score={score_val:.0f}[/]  "
                f"[[{mode_color}]{sf.include_mode}[/]]  "
                f"[dim]{reason_str}[/]"
            )

        if near_cutoff_paths:
            console.print("\n[bold]Files near budget cutoff[/] [dim](would appear with larger budget):[/]")
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

        if excluded_receipts:
            console.print("\n[bold]Excluded[/] [dim](top 5 by score):[/]")
            for r in excluded_receipts[:5]:
                score_val, _ = score_map.get(r.path, (0, []))
                console.print(
                    f"  [dim]-[/] {r.path:<50} "
                    f"[dim]score={score_val:.0f}   {r.reason}[/]"
                )

        console.print()
