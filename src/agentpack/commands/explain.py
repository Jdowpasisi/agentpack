from __future__ import annotations

from typing import Optional

import typer

from agentpack.application.pack_service import PackPlanner, PackRequest
from agentpack.core.context_pack import select_files
from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task
from agentpack.core.config import load_config


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
            summary_provider=summary_provider,
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

        console.print(f"\n[bold]Task:[/] [cyan]{resolved_task}[/]  [dim]mode={mode}  budget={plan.budget:,}[/]\n")

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

        if excluded_receipts:
            console.print(f"\n[bold]Excluded[/] [dim](top 5 by score):[/]")
            for r in excluded_receipts[:5]:
                score_val, _ = score_map.get(r.path, (0, []))
                console.print(
                    f"  [dim]-[/] {r.path:<50} "
                    f"[dim]score={score_val:.0f}   {r.reason}[/]"
                )

        console.print()
