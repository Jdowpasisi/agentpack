from __future__ import annotations

import json
import random
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    task_type: str = "general"


@dataclass
class CaseResult:
    case: BenchmarkCase
    packed_tokens: int
    raw_tokens: int           # all files (incl. ignored)
    after_ignore_tokens: int  # packable files only — honest baseline
    saving_pct: float         # vs raw
    saving_pct_honest: float  # vs after_ignore
    selected_paths: list[str]
    selected_tokens: dict[str, int]   # path → token count for noise calc
    changed_covered: int
    changed_total: int
    total_s: float
    phase_times: dict[str, float]
    rank_at_k: int | None = None   # min rank to see all expected_files; None if no expected
    noise_pct: float | None = None  # tokens on non-expected / packed; None if no expected
    random_precision: float | None = None
    random_recall: float | None = None
    random_f1: float | None = None
    missed_expected: list[dict[str, Any]] = field(default_factory=list)
    selected_modes: dict[str, str] = field(default_factory=dict)


@dataclass
class FixtureCase:
    fixture: str
    root: Path
    case: BenchmarkCase


def _sample_fixture_cases(fixtures_root: Path) -> list[FixtureCase]:
    specs = [
        (
            "py_fastapi_app",
            "fix FastAPI auth token validation",
            ["src/app/auth.py", "tests/test_auth.py"],
            "backend-api",
        ),
        (
            "py_fastapi_app",
            "add user profile API endpoint",
            ["src/app/main.py", "src/app/users.py", "tests/test_users.py"],
            "backend-api",
        ),
        (
            "nextjs_app",
            "fix Next.js auth helper and API client",
            ["src/lib/auth.ts", "src/lib/api.ts"],
            "frontend-web",
        ),
        (
            "nextjs_app",
            "debug dashboard page data loading",
            ["src/app/page.tsx", "src/lib/api.ts"],
            "frontend-web",
        ),
        (
            "mixed_repo",
            "fix TypeScript API serialization utility",
            ["src/ts/api.ts", "src/ts/utils.ts"],
            "typescript",
        ),
        (
            "mixed_repo",
            "fix Python utility parsing edge case",
            ["src/py/utils.py"],
            "python",
        ),
    ]

    cases: list[FixtureCase] = []
    for fixture, task, expected_files, task_type in specs:
        fixture_root = fixtures_root / fixture
        if fixture_root.exists():
            cases.append(
                FixtureCase(
                    fixture=fixture,
                    root=fixture_root,
                    case=BenchmarkCase(
                        task=task,
                        mode="balanced",
                        expected_files=expected_files,
                        task_type=task_type,
                    ),
                )
            )
    return cases


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
            task_type=raw.get("task_type", "general"),
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
        '# How to build a useful eval set:\n'
        '# 1. Add 5-20 real tasks from your repo history.\n'
        '# 2. Fill expected_files with files you actually edited for that task.\n'
        '# 3. Run: agentpack benchmark --compare\n'
        '# 4. Tune task text, .agentignore, and scoring weights until recall/token noise look sane.\n\n'
        '[[cases]]\n'
        'task = "fix auth token expiry"\n'
        'mode = "balanced"\n'
        'task_type = "backend-api"\n'
        '# expected_files = [\n'
        '#   "src/auth/token.py",\n'
        '#   "src/auth/session.py",\n'
        '# ]\n\n'
        '[[cases]]\n'
        'task = "add rate limiting to API endpoints"\n'
        'mode = "balanced"\n'
        'task_type = "backend-api"\n',
        encoding="utf-8",
    )
    return out


def _load_history_cases(root: Path, n: int) -> list[BenchmarkCase]:
    """Sample last N unique tasks from metrics.jsonl."""
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if not metrics_path.exists():
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for line in reversed(metrics_path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            task = rec.get("task", "").strip()
            mode = rec.get("mode", "balanced")
            if task and task not in seen_set:
                seen_set.add(task)
                seen.append((task, mode))
                if len(seen) >= n:
                    break
        except json.JSONDecodeError:
            pass
    return [BenchmarkCase(task=t, mode=m, task_type="history") for t, m in seen]


def _random_baseline(
    packable_paths: list[str],
    packable_tokens: dict[str, int],
    expected_files: list[str],
    budget: int,
) -> tuple[list[str], float, float, float]:
    """Random file selection at same budget. Returns (selected, precision, recall, f1)."""
    shuffled = list(packable_paths)
    random.shuffle(shuffled)
    selected: list[str] = []
    used = 0
    for p in shuffled:
        tok = packable_tokens.get(p, 50)
        if used + tok <= budget:
            selected.append(p)
            used += tok

    expected = set(expected_files)
    sel_set = set(selected)
    if not expected or not sel_set:
        return selected, 0.0, 0.0, 0.0
    tp = len(sel_set & expected)
    p = tp / len(sel_set)
    r = tp / len(expected)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return selected, p, r, f1


def _run_case(root: Path, case: BenchmarkCase) -> CaseResult:
    from agentpack.application.pack_service import PackPlanner, PackRequest, _sf_tokens
    from agentpack.core.config import load_config

    cfg = load_config(root)

    request = PackRequest(
        root=root,
        agent="generic",
        task=case.task,
        mode=case.mode,
        budget=0,
        since=None,
        refresh=False,
    )

    t0 = time.perf_counter()
    plan = PackPlanner().plan(request)
    total_s = time.perf_counter() - t0

    packed_tokens = sum(_sf_tokens(sf) for sf in plan.selected)
    raw_tokens = sum(f.estimated_tokens for f in plan.scan_result.all_files)
    after_ignore_tokens = sum(f.estimated_tokens for f in plan.scan_result.packable)
    saving_pct = (1 - packed_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0.0
    saving_pct_honest = (1 - packed_tokens / after_ignore_tokens) * 100 if after_ignore_tokens > 0 else 0.0

    selected_paths = [sf.path for sf in plan.selected]
    selected_set = set(selected_paths)
    selected_tokens = {sf.path: _sf_tokens(sf) for sf in plan.selected}
    selected_modes = {sf.path: _selected_mode(sf) for sf in plan.selected}

    changed_covered = len(plan.all_changed & selected_set)
    changed_total = len(plan.all_changed)

    # Rank@K: min rank in scored list to cover all expected files
    rank_at_k: int | None = None
    noise_pct: float | None = None
    rand_p = rand_r = rand_f1 = None

    if case.expected_files:
        expected_set = set(case.expected_files)
        scored_paths = [fi.path for fi, _score, _reasons in plan.scored]
        scored_map = {
            fi.path: {"rank": rank, "score": score, "reasons": reasons}
            for rank, (fi, score, reasons) in enumerate(plan.scored, 1)
        }
        all_file_map = {fi.path: fi for fi in plan.scan_result.all_files}
        receipt_map = {receipt.path: receipt.reason for receipt in plan.receipts}
        found: set[str] = set()
        for k, path in enumerate(scored_paths, 1):
            if path in expected_set:
                found.add(path)
            if found >= expected_set:
                rank_at_k = k
                break

        expected_tokens = sum(selected_tokens.get(p, 0) for p in selected_set & expected_set)
        noise_pct = (1 - expected_tokens / packed_tokens) * 100 if packed_tokens > 0 else 0.0

        packable_paths = [f.path for f in plan.scan_result.packable]
        packable_token_map = {f.path: f.estimated_tokens for f in plan.scan_result.packable}
        budget = cfg.context.default_budget
        _, rand_p, rand_r, rand_f1 = _random_baseline(packable_paths, packable_token_map, case.expected_files, budget)

        missed_expected = []
        for expected_path in sorted(expected_set - selected_set):
            fi = all_file_map.get(expected_path)
            scored_info = scored_map.get(expected_path)
            status = _miss_status(
                fi=fi,
                expected_path=expected_path,
                receipt_map=receipt_map,
                scored_info=scored_info,
                changed_files_source=plan.changed_files_source,
            )
            missed_expected.append({
                "path": expected_path,
                "status": status,
                "rank": scored_info["rank"] if scored_info else None,
                "score": round(scored_info["score"], 1) if scored_info else None,
                "reasons": scored_info["reasons"][:4] if scored_info else [],
                "basis": plan.changed_files_source,
            })
    else:
        missed_expected = []

    return CaseResult(
        case=case,
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        after_ignore_tokens=after_ignore_tokens,
        saving_pct=saving_pct,
        saving_pct_honest=saving_pct_honest,
        selected_paths=selected_paths,
        selected_tokens=selected_tokens,
        selected_modes=selected_modes,
        changed_covered=changed_covered,
        changed_total=changed_total,
        total_s=total_s,
        phase_times=plan.phase_times,
        rank_at_k=rank_at_k,
        noise_pct=noise_pct,
        random_precision=rand_p,
        random_recall=rand_r,
        random_f1=rand_f1,
        missed_expected=missed_expected,
    )


def _precision_recall(result: CaseResult) -> tuple[float, float, float]:
    expected = set(result.case.expected_files)
    if not expected:
        return 0.0, 0.0, 0.0
    selected = set(result.selected_paths)
    tp = len(selected & expected)
    p = tp / len(selected) if selected else 0.0
    r = tp / len(expected)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def _miss_status(
    *,
    fi: Any,
    expected_path: str,
    receipt_map: dict[str, str],
    scored_info: dict[str, Any] | None,
    changed_files_source: str,
) -> str:
    suffix = ""
    if changed_files_source.startswith("no live changes"):
        suffix = "; no live changed-file signal"
    if fi is None:
        return "not found in scanned files"
    if fi.ignored or fi.binary:
        return "ignored or binary"
    if expected_path in receipt_map:
        return receipt_map[expected_path] + suffix
    if scored_info:
        if scored_info["score"] <= 0:
            return "scored too low" + suffix
        return "ranked but not selected" + suffix
    return "not scored" + suffix


def _persist_result(root: Path, result: CaseResult) -> None:
    out = root / ".agentpack" / "benchmark_results.jsonl"
    p, r, f1 = _precision_recall(result) if result.case.expected_files else (None, None, None)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": result.case.task,
        "task_type": result.case.task_type,
        "mode": result.case.mode,
        "packed_tokens": result.packed_tokens,
        "raw_tokens": result.raw_tokens,
        "after_ignore_tokens": result.after_ignore_tokens,
        "saving_pct": round(result.saving_pct, 1),
        "saving_pct_honest": round(result.saving_pct_honest, 1),
        "files_selected": len(result.selected_paths),
        "mode_counts": _mode_counts(result.selected_modes),
        "changed_covered": result.changed_covered,
        "changed_total": result.changed_total,
        "total_s": round(result.total_s, 3),
        "phases": {k: round(v, 3) for k, v in result.phase_times.items()},
        "precision": round(p, 3) if p is not None else None,
        "recall": round(r, 3) if r is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
        "rank_at_k": result.rank_at_k,
        "noise_pct": round(result.noise_pct, 1) if result.noise_pct is not None else None,
        "random_f1": round(result.random_f1, 3) if result.random_f1 is not None else None,
        "misses": result.missed_expected,
    }
    try:
        with out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _print_case_detail(result: CaseResult, show_misses: bool = False) -> None:
    has_gt = bool(result.case.expected_files)
    p, r, f1 = _precision_recall(result) if has_gt else (0.0, 0.0, 0.0)

    console.print(
        f"\n[bold cyan]{result.case.task}[/]  "
        f"[dim]mode={result.case.mode} type={result.case.task_type}[/]"
    )

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style="dim")
    tbl.add_column(justify="right", style="bold")
    tbl.add_row("packed tokens", f"{result.packed_tokens:,}")
    tbl.add_row("raw tokens (all files)", f"{result.raw_tokens:,}")
    tbl.add_row("after ignore tokens", f"{result.after_ignore_tokens:,}")
    tbl.add_row("saving vs raw", f"[green]{result.saving_pct:.1f}%[/]")
    tbl.add_row("saving vs after-ignore", f"[cyan]{result.saving_pct_honest:.1f}%[/]")
    tbl.add_row("files selected", str(len(result.selected_paths)))
    tbl.add_row("mode mix", _format_mode_counts(_mode_counts(result.selected_modes)))
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
        if result.rank_at_k is not None:
            console.print(f"  rank@K (all expected covered at rank) [bold]{result.rank_at_k}[/]")
        else:
            console.print("  rank@K  [dim]expected files not all found in scored list[/]")
        if result.noise_pct is not None:
            console.print(f"  noise (tokens on non-expected files) [bold]{result.noise_pct:.1f}%[/]")
        if result.random_f1 is not None:
            lift = f1 - result.random_f1
            color = "green" if lift >= 0 else "red"
            console.print(
                f"  random baseline F1 [dim]{result.random_f1:.1%}[/]  "
                f"ranker lift [{color}]{lift:+.1%}[/{color}]"
            )
        expected_set = set(result.case.expected_files)
        selected_set = set(result.selected_paths)
        hits = expected_set & selected_set
        misses = expected_set - selected_set
        if hits:
            console.print("  [green]hit:[/]  " + ", ".join(sorted(hits)))
        if misses:
            console.print("  [red]miss:[/] " + ", ".join(sorted(misses)))
        if show_misses and result.missed_expected:
            console.print("  [yellow]miss details:[/]")
            for miss in result.missed_expected:
                rank = miss["rank"] if miss["rank"] is not None else "-"
                score = miss["score"] if miss["score"] is not None else "-"
                reasons = ", ".join(miss["reasons"]) if miss["reasons"] else "no scoring reasons"
                console.print(
                    f"    {miss['path']}  status={miss['status']}  "
                    f"rank={rank}  score={score}  why={reasons}"
                )

    console.print("  [dim]top files:[/] " + ", ".join(result.selected_paths[:5]))


def _mode_counts(selected_modes: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mode in selected_modes.values():
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def _selected_mode(sf: Any) -> str:
    mode = getattr(sf, "include_mode", "summary")
    return mode if isinstance(mode, str) else "summary"


def _format_mode_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    order = ("full", "diff", "symbols", "skeleton", "summary")
    return ", ".join(f"{mode}:{counts[mode]}" for mode in order if counts.get(mode))


def _print_summary_table(results: list[CaseResult]) -> None:
    has_gt = any(r.case.expected_files for r in results)

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=40)
    tbl.add_column("mode", width=9)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("vs raw", justify="right")
    tbl.add_column("vs ignore", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")
    if has_gt:
        tbl.add_column("P", justify="right")
        tbl.add_column("R", justify="right")
        tbl.add_column("F1", justify="right")
        tbl.add_column("rand F1", justify="right")
        tbl.add_column("rank@K", justify="right")
        tbl.add_column("noise%", justify="right")

    for r in results:
        p, rec, f1 = _precision_recall(r) if r.case.expected_files else (0.0, 0.0, 0.0)
        row = [
            r.case.task[:38],
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            f"{r.saving_pct_honest:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        ]
        if has_gt:
            row += [
                f"{p:.1%}" if r.case.expected_files else "—",
                f"{rec:.1%}" if r.case.expected_files else "—",
                f"{f1:.1%}" if r.case.expected_files else "—",
                f"{r.random_f1:.1%}" if r.random_f1 is not None else "—",
                str(r.rank_at_k) if r.rank_at_k is not None else "—",
                f"{r.noise_pct:.0f}%" if r.noise_pct is not None else "—",
            ]
        tbl.add_row(*row)

    console.print()
    console.print(tbl)


def _print_task_type_summary(results: list[CaseResult]) -> None:
    grouped: dict[str, list[CaseResult]] = {}
    for result in results:
        if result.case.expected_files:
            grouped.setdefault(result.case.task_type, []).append(result)
    if not grouped:
        return

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task type", max_width=28)
    tbl.add_column("cases", justify="right")
    tbl.add_column("avg P", justify="right")
    tbl.add_column("avg R", justify="right")
    tbl.add_column("avg F1", justify="right")
    tbl.add_column("avg noise", justify="right")

    for task_type, rows in sorted(grouped.items()):
        metrics = [_precision_recall(row) for row in rows]
        avg_p = sum(item[0] for item in metrics) / len(metrics)
        avg_r = sum(item[1] for item in metrics) / len(metrics)
        avg_f1 = sum(item[2] for item in metrics) / len(metrics)
        noise_values = [row.noise_pct for row in rows if row.noise_pct is not None]
        avg_noise = sum(noise_values) / len(noise_values) if noise_values else None
        tbl.add_row(
            task_type,
            str(len(rows)),
            f"{avg_p:.1%}",
            f"{avg_r:.1%}",
            f"{avg_f1:.1%}",
            f"{avg_noise:.0f}%" if avg_noise is not None else "-",
        )

    console.print("\n[bold]By Task Type[/]")
    console.print(tbl)


def _print_miss_details(results: list[CaseResult]) -> None:
    rows = [miss | {"task": result.case.task[:30]} for result in results for miss in result.missed_expected]
    if not rows:
        return

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=30)
    tbl.add_column("missed file", max_width=42)
    tbl.add_column("status", max_width=24)
    tbl.add_column("rank", justify="right")
    tbl.add_column("score", justify="right")
    tbl.add_column("why", max_width=40)

    for row in rows:
        tbl.add_row(
            row["task"],
            row["path"],
            row["status"],
            str(row["rank"]) if row["rank"] is not None else "-",
            str(row["score"]) if row["score"] is not None else "-",
            ", ".join(row["reasons"]) if row["reasons"] else "-",
        )

    console.print("\n[bold]Miss Details[/]")
    console.print(tbl)


def _print_fixture_summary_table(results: list[CaseResult]) -> None:
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("fixture task", max_width=42)
    tbl.add_column("mode", width=9)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("R", justify="right")
    tbl.add_column("F1", justify="right")
    tbl.add_column("rank@K", justify="right")
    tbl.add_column("noise", justify="right")

    for result in results:
        _p, recall, f1 = _precision_recall(result)
        tbl.add_row(
            result.case.task[:40],
            result.case.mode,
            f"{result.packed_tokens:,}",
            f"{recall:.0%}",
            f"{f1:.0%}",
            str(result.rank_at_k) if result.rank_at_k is not None else "-",
            f"{result.noise_pct:.0f}%" if result.noise_pct is not None else "-",
        )

    console.print()
    console.print(tbl)


def _print_compare_table(task: str, results: list[CaseResult]) -> None:
    console.print(f"\n[bold]Mode comparison:[/] [cyan]{task}[/]\n")

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("mode", width=10)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("vs raw", justify="right")
    tbl.add_column("vs ignore", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")

    for r in results:
        tbl.add_row(
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            f"{r.saving_pct_honest:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        )
    console.print(tbl)


def _copy_fixture(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".agentpack", ".pytest_cache"),
    )


def register(app: typer.Typer) -> None:
    @app.command()
    def benchmark(
        task: str = typer.Option("", "--task", help="Single task to benchmark (skips cases file)."),
        mode: str = typer.Option("balanced", "--mode", help="Mode for single-task run (minimal|balanced|deep)."),
        cases: str = typer.Option("", "--cases", help="Path to TOML cases file (default: .agentpack/benchmark.toml)."),
        compare: bool = typer.Option(False, "--compare", is_flag=True, help="Compare minimal/balanced/deep for each task."),
        init: bool = typer.Option(False, "--init", is_flag=True, help="Scaffold a benchmark.toml and exit."),
        from_history: int = typer.Option(0, "--from-history", help="Sample last N unique tasks from metrics.jsonl history."),
        sample_fixtures: bool = typer.Option(False, "--sample-fixtures", is_flag=True, help="Run bundled FastAPI/Next.js/mixed-repo fixture evals from a source checkout."),
        misses: bool = typer.Option(False, "--misses", is_flag=True, help="Show diagnostics for expected files that were not selected."),
    ) -> None:
        """Benchmark file selection quality and token efficiency across tasks."""
        root = _root()

        if init:
            out = _scaffold_cases(root)
            console.print(f"[green]✓[/] Created [bold]{out}[/]")
            console.print("  Edit the file to add your tasks and expected files, then run [bold]agentpack benchmark[/].")
            return

        if sample_fixtures:
            fixtures_root = root / "tests" / "fixtures"
            fixture_cases = _sample_fixture_cases(fixtures_root)
            if not fixture_cases:
                console.print(f"[yellow]No bundled fixture repos found at {fixtures_root}[/]")
                console.print("  This demo is available from an AgentPack source checkout. For your own repo, run [bold]agentpack benchmark --init[/].")
                raise typer.Exit(1)

            if compare:
                expanded_fixtures: list[FixtureCase] = []
                for fixture_case in fixture_cases:
                    for fixture_mode in ("minimal", "balanced", "deep"):
                        expanded_fixtures.append(
                            FixtureCase(
                                fixture=fixture_case.fixture,
                                root=fixture_case.root,
                case=BenchmarkCase(
                    task=fixture_case.case.task,
                    mode=fixture_mode,
                    expected_files=fixture_case.case.expected_files,
                    task_type=fixture_case.case.task_type,
                ),
                            )
                        )
                fixture_cases = expanded_fixtures

            console.print(f"\n[bold]Running {len(fixture_cases)} sample fixture benchmark case(s)...[/]\n")

            results: list[CaseResult] = []
            with tempfile.TemporaryDirectory(prefix="agentpack-benchmark-") as temp_dir:
                temp_root = Path(temp_dir)
                for i, fixture_case in enumerate(fixture_cases, 1):
                    case_root = temp_root / f"{i:02d}-{fixture_case.fixture}"
                    _copy_fixture(fixture_case.root, case_root)
                    label = f"[{i}/{len(fixture_cases)}] {fixture_case.fixture}: {fixture_case.case.task[:42]}  mode={fixture_case.case.mode}"
                    with console.status(f"[dim]{label}[/]"):
                        try:
                            result = _run_case(case_root, fixture_case.case)
                            result.case.task = f"{fixture_case.fixture}: {result.case.task}"
                            results.append(result)
                        except Exception as e:
                            console.print(f"[red]Error on fixture case '{fixture_case.case.task}': {e}[/]")

            if not results:
                raise typer.Exit(1)

            console.print("[dim]Sample fixtures are small source-checkout evals. Use your own benchmark.toml for true third-party repo scores.[/]")
            fixture_names = ", ".join(sorted({fixture_case.fixture for fixture_case in fixture_cases}))
            console.print(f"[dim]Fixtures:[/] {fixture_names}")
            if len(results) == 1:
                _print_case_detail(results[0], show_misses=misses)
            else:
                console.print("\n[bold]Summary[/]")
                _print_fixture_summary_table(results)
                _print_task_type_summary(results)
                if misses:
                    _print_miss_details(results)
            return

        # Build case list
        if from_history > 0:
            bench_cases = _load_history_cases(root, from_history)
            if not bench_cases:
                console.print("[yellow]No task history found in metrics.jsonl. Run agentpack pack first.[/]")
                raise typer.Exit(1)
        elif task:
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
                    expanded.append(
                        BenchmarkCase(
                            task=c.task,
                            mode=m,
                            expected_files=c.expected_files,
                            task_type=c.task_type,
                        )
                    )
            bench_cases = expanded

        console.print(f"\n[bold]Running {len(bench_cases)} benchmark case(s)...[/]\n")

        results: list[CaseResult] = []
        for i, c in enumerate(bench_cases, 1):
            label = f"[{i}/{len(bench_cases)}] {c.task[:50]}  mode={c.mode}"
            with console.status(f"[dim]{label}[/]"):
                try:
                    r = _run_case(root, c)
                    _persist_result(root, r)
                    results.append(r)
                except Exception as e:
                    console.print(f"[red]Error on case '{c.task}': {e}[/]")

        if not results:
            raise typer.Exit(1)

        # Output
        if compare and len(set(r.case.task for r in results)) == 1:
            _print_compare_table(results[0].case.task, results)
            if misses:
                _print_miss_details(results)
        elif len(results) == 1:
            _print_case_detail(results[0], show_misses=misses)
        else:
            if not compare:
                for r in results:
                    _print_case_detail(r, show_misses=misses)
            console.print("\n[bold]Summary[/]")
            _print_summary_table(results)
            _print_task_type_summary(results)
            if misses:
                _print_miss_details(results)
