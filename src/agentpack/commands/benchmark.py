from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task


@dataclass
class BenchmarkCase:
    task: str
    mode: str = "balanced"
    expected_files: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: BenchmarkCase
    packed_tokens: int
    raw_tokens: int
    saving_pct: float
    selected_paths: list[str]
    changed_covered: int      # # changed files that were selected
    changed_total: int        # total changed files detected
    total_s: float
    phase_times: dict[str, float]


def _load_cases(path: Path) -> list[BenchmarkCase]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cases: list[BenchmarkCase] = []
    for raw in data.get("cases", []):
        cases.append(BenchmarkCase(
            task=raw["task"],
            mode=raw.get("mode", "balanced"),
            expected_files=raw.get("expected_files", []),
        ))
    return cases


def _scaffold_cases(root: Path) -> Path:
    out = root / ".agentpack" / "benchmark.toml"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '# AgentPack benchmark cases\n'
        '# Each case runs a pack and measures token savings, speed, and\n'
        '# selection quality. Add expected_files for precision/recall scoring.\n\n'
        '[[cases]]\n'
        'task = "fix auth token expiry"\n'
        'mode = "balanced"\n'
        '# expected_files = [\n'
        '#   "src/auth/token.py",\n'
        '#   "src/auth/session.py",\n'
        '# ]\n\n'
        '[[cases]]\n'
        'task = "add rate limiting to API endpoints"\n'
        'mode = "balanced"\n',
        encoding="utf-8",
    )
    return out


def _run_case(root: Path, case: BenchmarkCase) -> CaseResult:
    from agentpack.application.pack_service import PackPlanner, PackRequest, _sf_tokens
    from agentpack.core.token_estimator import estimate_tokens

    request = PackRequest(
        root=root,
        agent="generic",
        task=case.task,
        mode=case.mode,
        budget=0,
        since=None,
        refresh=False,
        summary_provider="offline",
    )

    t0 = time.perf_counter()
    plan = PackPlanner().plan(request)
    total_s = time.perf_counter() - t0

    packed_tokens = sum(_sf_tokens(sf) for sf in plan.selected)
    raw_tokens = sum(f.estimated_tokens for f in plan.scan_result.all_files)
    saving_pct = (1 - packed_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0.0

    selected_paths = [sf.path for sf in plan.selected]
    selected_set = set(selected_paths)

    changed_covered = len(plan.all_changed & selected_set)
    changed_total = len(plan.all_changed)

    return CaseResult(
        case=case,
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        saving_pct=saving_pct,
        selected_paths=selected_paths,
        changed_covered=changed_covered,
        changed_total=changed_total,
        total_s=total_s,
        phase_times=plan.phase_times,
    )


def _precision_recall(result: CaseResult) -> tuple[float, float, float]:
    """Returns (precision, recall, f1). Requires expected_files on the case."""
    expected = set(result.case.expected_files)
    if not expected:
        return 0.0, 0.0, 0.0
    selected = set(result.selected_paths)
    tp = len(selected & expected)
    p = tp / len(selected) if selected else 0.0
    r = tp / len(expected)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def _print_case_detail(result: CaseResult) -> None:
    has_gt = bool(result.case.expected_files)
    p, r, f1 = _precision_recall(result) if has_gt else (0.0, 0.0, 0.0)

    console.print(f"\n[bold cyan]{result.case.task}[/]  [dim]mode={result.case.mode}[/]")

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style="dim")
    tbl.add_column(justify="right", style="bold")
    tbl.add_row("packed tokens", f"{result.packed_tokens:,}")
    tbl.add_row("raw tokens", f"{result.raw_tokens:,}")
    tbl.add_row("saving", f"[green]{result.saving_pct:.1f}%[/]")
    tbl.add_row("files selected", str(len(result.selected_paths)))
    if result.changed_total > 0:
        cov_pct = result.changed_covered / result.changed_total * 100
        tbl.add_row("changed files covered", f"{result.changed_covered}/{result.changed_total}  ({cov_pct:.0f}%)")
    tbl.add_row("total time", f"{result.total_s:.2f}s")
    console.print(tbl)

    if result.phase_times:
        phases = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        phases.add_column("phase", style="dim")
        phases.add_column("time", justify="right")
        for phase, t in result.phase_times.items():
            phases.add_row(phase, f"{t:.3f}s")
        console.print(phases)

    if has_gt:
        console.print(
            f"  precision [bold]{p:.1%}[/]  "
            f"recall [bold]{r:.1%}[/]  "
            f"F1 [bold]{f1:.1%}[/]"
        )
        expected_set = set(result.case.expected_files)
        selected_set = set(result.selected_paths)
        hits = expected_set & selected_set
        misses = expected_set - selected_set
        if hits:
            console.print(f"  [green]hit:[/]  " + ", ".join(sorted(hits)))
        if misses:
            console.print(f"  [red]miss:[/] " + ", ".join(sorted(misses)))

    console.print(f"  [dim]top files:[/] " + ", ".join(result.selected_paths[:5]))


def _print_summary_table(results: list[CaseResult]) -> None:
    has_gt = any(r.case.expected_files for r in results)

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=40)
    tbl.add_column("mode", width=9)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("saving", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")
    if has_gt:
        tbl.add_column("P", justify="right")
        tbl.add_column("R", justify="right")
        tbl.add_column("F1", justify="right")

    for r in results:
        p, rec, f1 = _precision_recall(r) if r.case.expected_files else (0.0, 0.0, 0.0)
        row = [
            r.case.task[:38],
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        ]
        if has_gt:
            row += [
                f"{p:.1%}" if r.case.expected_files else "—",
                f"{rec:.1%}" if r.case.expected_files else "—",
                f"{f1:.1%}" if r.case.expected_files else "—",
            ]
        tbl.add_row(*row)

    console.print()
    console.print(tbl)


def _print_compare_table(task: str, results: list[CaseResult]) -> None:
    """Side-by-side mode comparison for a single task."""
    console.print(f"\n[bold]Mode comparison:[/] [cyan]{task}[/]\n")

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("mode", width=10)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("saving", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")

    for r in results:
        tbl.add_row(
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        )
    console.print(tbl)


def register(app: typer.Typer) -> None:
    @app.command()
    def benchmark(
        task: str = typer.Option("", "--task", help="Single task to benchmark (skips cases file)."),
        mode: str = typer.Option("balanced", "--mode", help="Mode for single-task run (minimal|balanced|deep)."),
        cases: str = typer.Option("", "--cases", help="Path to TOML cases file (default: .agentpack/benchmark.toml)."),
        compare: bool = typer.Option(False, "--compare", is_flag=True, help="Compare minimal/balanced/deep for each task."),
        init: bool = typer.Option(False, "--init", is_flag=True, help="Scaffold a benchmark.toml and exit."),
    ) -> None:
        """Benchmark file selection quality and token efficiency across tasks."""
        root = _root()

        if init:
            out = _scaffold_cases(root)
            console.print(f"[green]✓[/] Created [bold]{out}[/]")
            console.print("  Edit the file to add your tasks and expected files, then run [bold]agentpack benchmark[/].")
            return

        # Build case list
        if task:
            resolved = _resolve_task(task) if task == "auto" else task
            bench_cases = [BenchmarkCase(task=resolved, mode=mode)]
        else:
            cases_path = Path(cases) if cases else root / ".agentpack" / "benchmark.toml"
            if not cases_path.exists():
                console.print(f"[yellow]No cases file found at {cases_path}[/]")
                console.print("  Run [bold]agentpack benchmark --init[/] to scaffold one, or use [bold]--task \"...\"[/]")
                raise typer.Exit(1)
            bench_cases = _load_cases(cases_path)
            if not bench_cases:
                console.print("[yellow]No cases defined in benchmark file.[/]")
                raise typer.Exit(1)

        # Expand for compare mode
        if compare:
            expanded: list[BenchmarkCase] = []
            for c in bench_cases:
                for m in ("minimal", "balanced", "deep"):
                    expanded.append(BenchmarkCase(task=c.task, mode=m, expected_files=c.expected_files))
            bench_cases = expanded

        console.print(f"\n[bold]Running {len(bench_cases)} benchmark case(s)...[/]\n")

        results: list[CaseResult] = []
        for i, c in enumerate(bench_cases, 1):
            label = f"[{i}/{len(bench_cases)}] {c.task[:50]}  mode={c.mode}"
            with console.status(f"[dim]{label}[/]"):
                try:
                    r = _run_case(root, c)
                    results.append(r)
                except Exception as e:
                    console.print(f"[red]Error on case '{c.task}': {e}[/]")

        if not results:
            raise typer.Exit(1)

        # Output
        if compare and len(set(r.case.task for r in results)) == 1:
            _print_compare_table(results[0].case.task, results)
        elif len(results) == 1:
            _print_case_detail(results[0])
        else:
            if not compare:
                for r in results:
                    _print_case_detail(r)
            console.print("\n[bold]Summary[/]")
            _print_summary_table(results)
