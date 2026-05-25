from __future__ import annotations

from pathlib import Path
import time

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root
from agentpack.core.evals import (
    FAILURE_CLASSES,
    append_captured_eval_case,
    compare_eval_variants,
    default_eval_cases_path,
    eval_results_path,
    eval_watch_fingerprint,
    load_eval_cases,
    load_eval_result_records,
    persist_eval_results,
    run_eval_suite,
    scaffold_eval_cases,
    write_eval_ci_template,
    write_eval_report,
)


def register(app: typer.Typer) -> None:
    @app.command(name="eval")
    def eval_command(
        init: bool = typer.Option(False, "--init", is_flag=True, help="Scaffold .agentpack/evals.toml and exit."),
        cases: str = typer.Option("", "--cases", help="Path to eval TOML file (default: .agentpack/evals.toml)."),
        case: str = typer.Option("", "--case", help="Run one eval case by id."),
        prove_targets: bool = typer.Option(False, "--prove-targets", is_flag=True, help="Exit non-zero when any eval case fails."),
        capture: str = typer.Option("", "--capture", help="Append a case from current git diff using this id."),
        failure_class: str = typer.Option("context", "--failure-class", help=f"Failure class ({' | '.join(FAILURE_CLASSES)})."),
        failure_source: str = typer.Option("agent_failed", "--failure-source", help="Failure source for captured cases."),
        check: list[str] | None = typer.Option(None, "--check", help="Deterministic command check for --capture. Repeatable."),
        task: str = typer.Option("", "--task", help="Task text for --capture."),
        base_ref: str = typer.Option("HEAD", "--base-ref", help="Git base ref for diff checks."),
        report: bool = typer.Option(False, "--report", is_flag=True, help="Write benchmarks/results/YYYY-MM-DD-eval.md."),
        ci_template: bool = typer.Option(False, "--ci-template", is_flag=True, help="Scaffold .github/workflows/agentpack-eval.yml and exit."),
        variant: str = typer.Option("agentpack", "--variant", help="Result variant label, e.g. baseline or agentpack."),
        compare_variants: str = typer.Option("", "--compare-variants", help="Compare latest results as BASELINE:VARIANT."),
        replay: bool = typer.Option(False, "--replay", is_flag=True, help="Run cases in isolated git worktrees using captured patch_file artifacts."),
        watch: bool = typer.Option(False, "--watch", is_flag=True, help="Rerun evals when git diff state changes."),
        interval: float = typer.Option(2.0, "--interval", help="Watch polling interval in seconds."),
        max_runs: int = typer.Option(0, "--max-runs", help="Maximum watch runs (0 = unlimited)."),
        until_pass: bool = typer.Option(False, "--until-pass", is_flag=True, help="Stop watch mode after all cases pass."),
        agent: str = typer.Option("", "--agent", help="Agent label to store with --capture metadata."),
        prompt_file: str = typer.Option("", "--prompt-file", help="Prompt artifact path to store with --capture."),
        context_file: str = typer.Option(".agentpack/context.md", "--context-file", help="Context artifact path to store with --capture."),
    ) -> None:
        """Run deterministic eval cases without using an LLM judge."""
        root = _root()
        cases_path = Path(cases) if cases else default_eval_cases_path(root)

        if compare_variants:
            _print_variant_comparison(root, compare_variants)
            return

        if ci_template:
            out = write_eval_ci_template(root)
            console.print(f"[green]✓[/] Created [bold]{out}[/]")
            return

        if init:
            out = scaffold_eval_cases(root)
            console.print(f"[green]✓[/] Created [bold]{out}[/]")
            console.print("  Edit it with real failures, then run [bold]agentpack eval[/].")
            return

        if capture:
            try:
                captured = append_captured_eval_case(
                    cases_path,
                    root=root,
                    case_id=capture,
                    failure_class=failure_class,
                    checks=check or [],
                    task=task,
                    failure_source=failure_source,
                    base_ref=base_ref,
                    agent=agent,
                    prompt_file=prompt_file,
                    context_file=context_file,
                )
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1) from exc
            console.print(f"[green]✓[/] Captured eval case [bold]{captured.id}[/] in [bold]{cases_path}[/]")
            console.print(f"  Required changed files: {len(captured.required_changed_files)}")
            if captured.patch_redaction_warnings:
                console.print(f"  [yellow]Redacted {len(captured.patch_redaction_warnings)} secret(s) from patch artifact.[/]")
            return

        if report and not cases_path.exists():
            records = load_eval_result_records(eval_results_path(root))
            out = write_eval_report(root, records)
            console.print(f"[green]✓[/] Wrote eval report: [bold]{out}[/]")
            return

        if not cases_path.exists():
            console.print(f"[yellow]No eval cases file found at {cases_path}[/]")
            console.print("  Run [bold]agentpack eval --init[/] to scaffold one.")
            raise typer.Exit(1)

        try:
            eval_cases = load_eval_cases(cases_path)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc

        if case:
            eval_cases = [item for item in eval_cases if item.id == case]
            if not eval_cases:
                console.print(f"[yellow]No eval case found with id: {case}[/]")
                raise typer.Exit(1)

        if not eval_cases:
            console.print("[yellow]No eval cases defined.[/]")
            raise typer.Exit(1)

        if watch:
            results = _watch_eval_cases(
                root,
                eval_cases,
                variant=variant,
                replay=replay,
                interval=interval,
                max_runs=max_runs,
                until_pass=until_pass,
                extra_paths=[cases_path],
            )
        else:
            results = _run_once(root, eval_cases, variant=variant, replay=replay)

        if report:
            records = load_eval_result_records(eval_results_path(root))
            out = write_eval_report(root, records)
            console.print(f"[green]✓[/] Wrote eval report: [bold]{out}[/]")

        if prove_targets and not all(result.passed for result in results):
            raise typer.Exit(2)


def _run_once(root: Path, eval_cases, *, variant: str, replay: bool):
    console.print(f"\n[bold]Running {len(eval_cases)} deterministic eval case(s)...[/]\n")
    results = run_eval_suite(root, eval_cases, variant=variant, replay=replay)
    persist_eval_results(root, results)
    _print_results(results)
    return results


def _watch_eval_cases(
    root: Path,
    eval_cases,
    *,
    variant: str,
    replay: bool,
    interval: float,
    max_runs: int,
    until_pass: bool,
    extra_paths: list[Path],
):
    if interval <= 0:
        console.print("[red]--interval must be greater than 0[/]")
        raise typer.Exit(1)
    if max_runs < 0:
        console.print("[red]--max-runs must be 0 or greater[/]")
        raise typer.Exit(1)

    console.print("[bold]Watching deterministic evals.[/] Press Ctrl-C to stop.")
    last_fingerprint = ""
    last_results = []
    patch_paths = [root / case.patch_file for case in eval_cases if case.patch_file]
    golden_paths = [root / golden.expected for case in eval_cases for golden in case.golden_files]
    watched_paths = extra_paths + patch_paths + golden_paths
    runs = 0
    try:
        while True:
            fingerprint = eval_watch_fingerprint(root, eval_cases, extra_paths=watched_paths)
            if fingerprint != last_fingerprint:
                runs += 1
                last_fingerprint = fingerprint
                last_results = _run_once(root, eval_cases, variant=variant, replay=replay)
                if until_pass and all(result.passed for result in last_results):
                    console.print("[green]✓[/] All eval cases pass; watch stopped.")
                    break
                if max_runs and runs >= max_runs:
                    break
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Eval watch stopped.[/]")
    return last_results


def _print_results(results) -> None:
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("case", max_width=32)
    tbl.add_column("status", width=8)
    tbl.add_column("class", max_width=18)
    tbl.add_column("checks", justify="right")
    tbl.add_column("changed", justify="right")
    tbl.add_column("lines", justify="right")
    tbl.add_column("time", justify="right")

    for result in results:
        status = "[green]pass[/]" if result.passed else "[red]fail[/]"
        failed = len(result.failed_checks)
        checks = f"{len(result.checks) - failed}/{len(result.checks)}"
        tbl.add_row(
            result.case.id,
            status,
            result.case.failure_class,
            checks,
            str(len(result.changed_files)),
            str(result.changed_lines),
            f"{result.duration_s:.2f}s",
        )

    console.print(tbl)
    for result in results:
        for check in result.failed_checks:
            detail = f": {check.detail}" if check.detail else ""
            console.print(f"  [red]![/] {result.case.id} / {check.name}{detail}", soft_wrap=True)


def _print_variant_comparison(root: Path, compare_variants: str) -> None:
    try:
        baseline, variant = compare_variants.split(":", 1)
    except ValueError as exc:
        console.print("[red]--compare-variants must use BASELINE:VARIANT, e.g. baseline:agentpack[/]")
        raise typer.Exit(1) from exc
    records = load_eval_result_records(eval_results_path(root))
    comparison = compare_eval_variants(records, baseline, variant)

    tbl = Table(title=f"Eval Variant Comparison: {baseline} → {variant}", box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("case", max_width=36)
    tbl.add_column(baseline, justify="center")
    tbl.add_column(variant, justify="center")
    tbl.add_column("status", max_width=12)
    for row in comparison["rows"]:
        tbl.add_row(
            row["case_id"],
            _pass_label(row["baseline_passed"]),
            _pass_label(row["variant_passed"]),
            row["status"],
        )
    console.print(tbl)
    console.print(
        f"  improved [bold green]{comparison['improved']}[/]  "
        f"regressed [bold red]{comparison['regressed']}[/]  "
        f"unchanged [bold]{comparison['unchanged']}[/]  "
        f"incomplete [bold yellow]{comparison['incomplete']}[/]"
    )


def _pass_label(value) -> str:
    if value is True:
        return "[green]pass[/]"
    if value is False:
        return "[red]fail[/]"
    return "[yellow]-[/]"
