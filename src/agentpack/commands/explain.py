from __future__ import annotations

import re
from typing import Optional

import typer
from rich.table import Table

from agentpack.application.pack_service import PackPlanner, PackRequest
from agentpack.core.context_pack import select_files
from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task
from agentpack.core.config import load_config, ScoringWeights
from agentpack.analysis.ranking import (
    ambiguous_task_terms,
    build_keyword_plan,
    extract_keyword_weights,
    generic_task_term_ratio,
    suggest_task_rewrite,
    _GENERIC_TASK_TERMS,
)

_SUPPORT_SIGNAL_PREFIXES = (
    "modified",
    "staged",
    "direct dependency of changed file",
    "reverse dependency",
    "recall neighbor",
    "historically co-changed",
    "has related tests",
    "test for",
    "workspace match",
)


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
    support_signals = [reason for reason in reasons if reason.startswith(_SUPPORT_SIGNAL_PREFIXES)]
    if not support_signals and any(
        reason in {
            "broad-task weak-signal dampening",
            "broad-task meta-summary dampening",
            "frontend-scope backend dampening",
            "frontend-scope backend suppression",
            "backend-scope frontend dampening",
            "backend-scope frontend suppression",
        }
        for reason in reasons
    ):
        console.print()
        console.print("  [bold]note:[/] weak semantic match only; no changed-file adjacency or dependency support signal")
    ambiguity = [reason for reason in reasons if reason.startswith(("ambiguous term cap", "ambiguous term restored by corroboration"))]
    if ambiguity:
        console.print()
        for line in ambiguity:
            console.print(f"  [bold]ambiguity:[/] {line}")
    console.print()


def _noise_report(task: str, plan: object) -> list[str]:
    keyword_plan = getattr(plan, "keyword_plan", None) or build_keyword_plan(task)
    keyword_weights = keyword_plan.weights if hasattr(keyword_plan, "weights") else extract_keyword_weights(task)
    generic_terms = list(getattr(keyword_plan, "generic_terms", ())) or sorted(term for term in keyword_weights if term in _GENERIC_TASK_TERMS)
    ambiguous_terms = list(getattr(keyword_plan, "ambiguous_terms", ())) or ambiguous_task_terms(task)
    learned_ambiguous = list(getattr(keyword_plan, "learned_ambiguous_terms", ()))
    specific_terms = sorted(
        term for term in keyword_weights
        if term not in _GENERIC_TASK_TERMS and term not in set(ambiguous_terms)
    )
    selected = list(plan.selected)  # type: ignore[attr-defined]
    summary_count = sum(1 for sf in selected if sf.include_mode == "summary")
    filename_count = sum(1 for sf in selected if "filename keyword match" in sf.reasons)
    symbol_count = sum(1 for sf in selected if "symbol keyword match" in sf.reasons)
    excluded = [r for r in plan.receipts if r.action == "excluded"]  # type: ignore[attr-defined]
    summary_cap = sum(1 for r in excluded if r.reason == "summary cap reached")
    score_floor = sum(1 for r in excluded if r.reason == "summary score below floor")
    strict_support = sum(1 for r in excluded if r.reason == "summary needs stronger support signal")

    lines = [
        "## Pack noise report",
        "",
        f"- generic task ratio: {generic_task_term_ratio(task):.0%}",
        f"- generic terms: {', '.join(generic_terms) if generic_terms else '(none)'}",
        f"- ambiguous terms: {', '.join(ambiguous_terms) if ambiguous_terms else '(none)'}",
        f"- learned ambiguous terms: {', '.join(learned_ambiguous) if learned_ambiguous else '(none)'}",
        f"- specific terms: {', '.join(specific_terms) if specific_terms else '(none)'}",
        f"- selected summaries: {summary_count}/{len(selected)}",
        f"- filename-match selections: {filename_count}/{len(selected)}",
        f"- symbol-match selections: {symbol_count}/{len(selected)}",
        f"- excluded by summary cap: {summary_cap}",
        f"- excluded by weak summary score: {score_floor}",
        f"- excluded by strict summary support: {strict_support}",
        "",
        "### Sharpen task wording",
        "",
    ]
    if generic_terms:
        lines.append("- Replace broad terms with subsystem, file, or symptom words.")
        lines.append(f"- Broad terms driving matches: {', '.join(generic_terms[:8])}.")
    else:
        lines.append("- Task terms are already specific; inspect changed files or score weights next.")
    if summary_count and selected and summary_count / len(selected) >= 0.7:
        lines.append("- Try `--mode minimal` for edit work, or add exact module/file names.")
    if filename_count and selected and filename_count / len(selected) >= 0.6:
        lines.append("- Filename matches dominate; add behavior words that appear inside target files.")
    if ambiguous_terms or generic_terms:
        lines.append(f"- Rewrite example: `{suggest_task_rewrite(task)}`.")
    return lines


def _print_noise_report(task: str, plan: object) -> None:
    for line in _noise_report(task, plan):
        console.print(line)


def _print_term_weights(plan: object) -> None:
    keyword_plan = getattr(plan, "keyword_plan", None)
    if keyword_plan is None:
        return
    term_table = Table(title="Task term weights", show_header=True)
    term_table.add_column("term", style="cyan")
    term_table.add_column("weight", justify="right")
    term_table.add_column("rarity", justify="right")
    term_table.add_column("kind")
    term_table.add_column("good", justify="right")
    term_table.add_column("bad", justify="right")
    for term, info in sorted(
        keyword_plan.term_stats.items(),
        key=lambda item: (-float(item[1].get("weight", 0.0)), item[0]),
    )[:20]:
        term_table.add_row(
            term,
            f"{float(info.get('weight', 0.0)):.2f}",
            f"{float(info.get('rarity', 0.0)):.2f}",
            str(info.get("kind", "")),
            str(int(info.get("good_runs", 0))),
            str(int(info.get("bad_runs", 0))),
        )
    console.print()
    console.print(term_table)

    if getattr(keyword_plan, "phrase_stats", None):
        phrase_table = Table(title="Task phrase weights", show_header=True)
        phrase_table.add_column("phrase", style="cyan")
        phrase_table.add_column("weight", justify="right")
        phrase_table.add_column("rarity", justify="right")
        phrase_table.add_column("kind")
        phrase_table.add_column("good", justify="right")
        phrase_table.add_column("bad", justify="right")
        for phrase, info in sorted(
            keyword_plan.phrase_stats.items(),
            key=lambda item: (-float(item[1].get("weight", 0.0)), item[0]),
        )[:12]:
            phrase_table.add_row(
                phrase,
                f"{float(info.get('weight', 0.0)):.2f}",
                f"{float(info.get('rarity', 0.0)):.2f}",
                str(info.get("kind", "")),
                str(int(info.get("good_runs", 0))),
                str(int(info.get("bad_runs", 0))),
            )
        console.print()
        console.print(phrase_table)


def _print_budget_plan(plan: object) -> None:
    from agentpack.application.pack_service import _sf_tokens

    selected = list(plan.selected)  # type: ignore[attr-defined]
    total_tokens = sum(_sf_tokens(sf) for sf in selected)
    console.print("[bold]Budget plan[/]")
    console.print(f"  selected: {len(selected)} files")
    console.print(f"  tokens:   {total_tokens:,}/{plan.budget:,}")  # type: ignore[attr-defined]
    console.print("")
    by_mode: dict[str, int] = {}
    by_mode_tokens: dict[str, int] = {}
    for sf in selected:
        by_mode[sf.include_mode] = by_mode.get(sf.include_mode, 0) + 1
        by_mode_tokens[sf.include_mode] = by_mode_tokens.get(sf.include_mode, 0) + _sf_tokens(sf)
    for mode, count in sorted(by_mode.items()):
        console.print(f"  {mode:<8} {count:>3} files  {by_mode_tokens[mode]:>6,} tokens")
    console.print("")
    console.print("[bold]Selected files by token value:[/]")
    for sf in sorted(selected, key=lambda item: item.score / max(_sf_tokens(item), 1), reverse=True)[:20]:
        tokens = _sf_tokens(sf)
        density = sf.score / max(tokens, 1)
        reason = sf.reasons[0] if sf.reasons else ""
        console.print(
            f"  {sf.path:<50} [{sf.include_mode:<8}] "
            f"score={sf.score:>5.0f} tokens={tokens:>5,} value/tok={density:.2f} "
            f"[dim]{reason}[/]"
        )


def register(app: typer.Typer) -> None:
    @app.command()
    def explain(
        task: str = typer.Option("auto", "--task", help="Task description, or 'auto' to infer from git."),
        mode: str = typer.Option("balanced", "--mode", help="Budget mode (lite|minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Token budget (0 = use config default)."),
        since: Optional[str] = typer.Option(None, "--since", help="Git ref to compare against (e.g. HEAD~1, main)."),
        file: Optional[str] = typer.Option(None, "--file", help="Show detailed score breakdown for a specific file."),
        omitted: bool = typer.Option(False, "--omitted", is_flag=True, help="Show top-10 excluded files and why."),
        why_noisy: bool = typer.Option(False, "--why-noisy", is_flag=True, help="Explain broad task terms and noisy selection signals."),
        budget_plan: bool = typer.Option(False, "--budget-plan", is_flag=True, help="Show selected modes, token costs, and value per token."),
    ) -> None:
        """Explain which files would be selected and why, without writing a context file."""
        if mode not in ("lite", "minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use lite|minimal|balanced|deep.[/]")
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
            min_summary_score=cfg.context.min_summary_score,
            max_summary_files=0,
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

        if why_noisy:
            console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")
            _print_noise_report(resolved_task, plan)
            _print_term_weights(plan)
            console.print()
            return

        if budget_plan:
            console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")
            _print_budget_plan(plan)
            console.print()
            return

        console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")

        console.print("[bold]Top selected files (ranked):[/]")
        for i, sf in enumerate(selected, 1):
            score_val, reasons = score_map.get(sf.path, (sf.score, sf.reasons))
            reason_str = ", ".join(reasons) if reasons else ""
            mode_color = {
                "full": "green",
                "diff": "cyan",
                "symbols": "yellow",
                "skeleton": "blue",
                "summary": "dim",
            }.get(sf.include_mode, "dim")
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
