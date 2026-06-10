from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.table import Table

from agentpack.commands._shared import console, _root


@dataclass
class TuningSuggestion:
    area: str
    finding: str
    suggestion: str


def register(app: typer.Typer) -> None:
    @app.command()
    def tune(
        from_benchmark: bool = typer.Option(True, "--from-benchmark/--no-benchmark", help="Use .agentpack/benchmark_results.jsonl."),
        write: bool = typer.Option(False, "--write", help="Write suggestions to .agentpack/tuning.md."),
    ) -> None:
        """Suggest tuning actions from benchmark misses and recent pack metrics."""
        root = _root()
        suggestions = _build_tuning_suggestions(root, include_benchmark=from_benchmark)
        if not suggestions:
            console.print("[green]No tuning suggestions found.[/]")
            console.print("Run `agentpack benchmark --init` and add expected_files for stronger guidance.")
            return

        table = Table(title="AgentPack Tuning Suggestions", show_header=True)
        table.add_column("Area", style="cyan")
        table.add_column("Finding", style="dim")
        table.add_column("Suggestion")
        for item in suggestions:
            table.add_row(item.area, item.finding, item.suggestion)
        console.print(table)

        if write:
            out = _write_tuning_report(root, suggestions)
            console.print(f"[green]✓[/] Wrote [bold]{out}[/]")


def _build_tuning_suggestions(root: Path, *, include_benchmark: bool = True) -> list[TuningSuggestion]:
    suggestions: list[TuningSuggestion] = []
    metrics = _load_jsonl(root / ".agentpack" / "metrics.jsonl")
    benchmark = _load_jsonl(root / ".agentpack" / "benchmark_results.jsonl") if include_benchmark else []
    eval_results = _load_jsonl(root / ".agentpack" / "eval_results.jsonl")

    accuracy_rows = [row for row in metrics if "selection_recall" in row][-10:]
    if accuracy_rows:
        avg_token_precision = _avg(row.get("selection_token_precision") for row in accuracy_rows)
        avg_context_precision = _avg(row.get("selection_token_context_precision") for row in accuracy_rows)
        avg_summary_precision = _avg(row.get("selection_token_precision_summary") for row in accuracy_rows)
        if avg_token_precision is not None and avg_token_precision < 0.3:
            suggestions.append(TuningSuggestion(
                "mode",
                f"token precision {avg_token_precision:.1%}",
                "Use `agentpack pack --mode minimal --task auto` for edit work until benchmark precision improves.",
            ))
        if avg_context_precision is not None and avg_context_precision > avg_token_precision:
            suggestions.append(TuningSuggestion(
                "metrics",
                f"context precision {avg_context_precision:.1%} vs edit precision {avg_token_precision:.1%}",
                "Treat read-only support files separately from edited-file precision; inspect support paths before ignoring them.",
            ))
        if avg_summary_precision is not None and avg_summary_precision < 0.1:
            suggestions.append(TuningSuggestion(
                "summaries",
                f"summary token precision {avg_summary_precision:.1%}",
                "Keep no-live summary suppression enabled; consider lowering balanced summary cap in `.agentpack/config.toml`.",
            ))

        noisy = _top_noisy_paths(accuracy_rows)
        for path, count in noisy[:5]:
            suggestions.append(TuningSuggestion(
                "noise",
                f"{path} appeared noisy {count}x",
                f"Run `agentpack explain --file {path} --task auto`; add generated/vendor paths to `.agentignore` if irrelevant.",
            ))

    if include_benchmark:
        if not benchmark:
            suggestions.append(TuningSuggestion(
                "benchmark",
                "no benchmark_results.jsonl",
                "Run `agentpack benchmark --init`, add historical tasks with expected_files, then run `agentpack benchmark --compare --misses`.",
            ))
        else:
            miss_status_counts: dict[str, int] = {}
            for row in benchmark[-20:]:
                for miss in row.get("misses", []) or []:
                    if isinstance(miss, dict):
                        status = str(miss.get("status") or "unknown")
                        miss_status_counts[status] = miss_status_counts.get(status, 0) + 1
            for status, count in sorted(miss_status_counts.items(), key=lambda item: (-item[1], item[0]))[:4]:
                if "ignored" in status:
                    suggestion = "Review `.agentignore`; expected files are being excluded."
                elif "budget" in status:
                    suggestion = "Try deep mode or reduce noisy summaries so expected files fit."
                elif "score" in status or "ranked" in status:
                    suggestion = "Improve task wording or scoring weights for this domain."
                else:
                    suggestion = "Use `agentpack explain --omitted --task <task>` to inspect the miss."
                suggestions.append(TuningSuggestion("benchmark misses", f"{count} miss(es): {status}", suggestion))

    if eval_results:
        class_counts: dict[str, int] = {}
        check_counts: dict[str, int] = {}
        for row in eval_results[-20:]:
            if row.get("passed") is False:
                failure_class = str(row.get("failure_class") or "unknown")
                class_counts[failure_class] = class_counts.get(failure_class, 0) + 1
                for check in row.get("failed_checks", []) or []:
                    if isinstance(check, str):
                        check_counts[check] = check_counts.get(check, 0) + 1
        for failure_class, count in sorted(class_counts.items(), key=lambda item: (-item[1], item[0]))[:4]:
            suggestions.append(TuningSuggestion(
                "eval failures",
                f"{count} failure(s): {failure_class}",
                "Use `agentpack eval --report` and inspect the failing deterministic checks before changing prompts or scoring.",
            ))
        for check, count in sorted(check_counts.items(), key=lambda item: (-item[1], item[0]))[:3]:
            suggestions.append(TuningSuggestion(
                "eval checks",
                f"{count} failure(s): {check}",
                "Strengthen or narrow this harness check if it is flaky; fix the agent workflow if it is deterministic.",
            ))

    return suggestions


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def _avg(values: Iterable[object]) -> float | None:
    nums = [float(value) for value in values if isinstance(value, int | float)]
    return sum(nums) / len(nums) if nums else None


def _top_noisy_paths(rows: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        for path in row.get("selection_noise_paths", []) or []:
            if isinstance(path, str):
                counts[path] = counts.get(path, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _write_tuning_report(root: Path, suggestions: list[TuningSuggestion]) -> Path:
    out = root / ".agentpack" / "tuning.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# AgentPack Tuning Suggestions", ""]
    for item in suggestions:
        lines.append(f"## {item.area}")
        lines.append("")
        lines.append(f"- finding: {item.finding}")
        lines.append(f"- suggestion: {item.suggestion}")
        lines.append("")
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
