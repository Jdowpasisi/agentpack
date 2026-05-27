from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from agentpack.commands._shared import console, _root
from agentpack.commands.tune import _build_tuning_suggestions
from agentpack.core.context_pack import load_pack_metadata


def register(app: typer.Typer) -> None:
    @app.command("diagnose-selection")
    def diagnose_selection(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
        write: bool = typer.Option(False, "--write", help="Write .agentpack/selection_diagnosis.md."),
    ) -> None:
        """Diagnose noisy or low-recall context selection."""
        root = _root()
        diagnosis = build_selection_diagnosis(root)
        if write:
            out = root / ".agentpack" / "selection_diagnosis.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_markdown_report(diagnosis), encoding="utf-8")
            diagnosis["written"] = str(out.relative_to(root))
        if json_output:
            typer.echo(json.dumps(diagnosis, indent=2, sort_keys=True))
            return
        _print_diagnosis(diagnosis)


def build_selection_diagnosis(root: Path) -> dict[str, Any]:
    meta = load_pack_metadata(root) or {}
    selected = [item for item in (meta.get("selected_files_meta") or []) if isinstance(item, dict)]
    largest = sorted(selected, key=lambda item: int(item.get("tokens") or 0), reverse=True)[:10]
    summary_count = sum(1 for item in selected if item.get("mode") == "summary")
    diagnostics: list[str] = []
    freshness = meta.get("freshness") or {}
    if freshness.get("generic_task_ratio", 0) and float(freshness.get("generic_task_ratio") or 0) >= 0.5:
        diagnostics.append("Task terms are broad; rewrite with concrete subsystem, file, route, or symptom words.")
    if selected and summary_count / len(selected) >= 0.7:
        diagnostics.append("Latest pack is mostly summaries; try `agentpack pack --mode minimal` or tighten task wording.")
    if freshness.get("mode_warning"):
        diagnostics.append(str(freshness["mode_warning"]))
    suggestions = [
        {"area": item.area, "finding": item.finding, "suggestion": item.suggestion}
        for item in _build_tuning_suggestions(root, include_benchmark=True)
    ]
    benchmark_misses = _recent_benchmark_misses(root)
    actions = list(diagnostics)
    actions.extend(item["suggestion"] for item in suggestions[:6])
    if not actions:
        actions.append("No obvious selection issue found. Add benchmark cases with expected_files for stronger diagnostics.")
    return {
        "task": meta.get("task", ""),
        "context_path": meta.get("context_path", ""),
        "selected_count": len(selected),
        "summary_count": summary_count,
        "largest_token_consumers": [
            {"path": item.get("path"), "mode": item.get("mode"), "tokens": item.get("tokens", 0)}
            for item in largest
        ],
        "diagnostics": diagnostics,
        "benchmark_misses": benchmark_misses,
        "suggestions": suggestions,
        "actions": actions[:10],
    }


def _recent_benchmark_misses(root: Path) -> list[dict[str, Any]]:
    path = root / ".agentpack" / "benchmark_results.jsonl"
    if not path.exists():
        return []
    misses: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-20:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for miss in row.get("misses", []) or []:
            if isinstance(miss, dict):
                item = dict(miss)
                item["task"] = row.get("task")
                misses.append(item)
    return misses[-10:]


def _print_diagnosis(diagnosis: dict[str, Any]) -> None:
    console.print("[bold]Selection diagnosis[/]")
    if diagnosis.get("task"):
        console.print(f"Task: {diagnosis['task']}")
    table = Table(show_header=True)
    table.add_column("file")
    table.add_column("mode")
    table.add_column("tokens", justify="right")
    for item in diagnosis["largest_token_consumers"][:8]:
        table.add_row(str(item["path"]), str(item["mode"]), str(item["tokens"]))
    console.print(table)
    console.print("[bold]Actions[/]")
    for action in diagnosis["actions"]:
        console.print(f"  - {action}")
    if diagnosis.get("written"):
        console.print(f"[green]✓[/] Wrote {diagnosis['written']}")


def _markdown_report(diagnosis: dict[str, Any]) -> str:
    lines = ["# AgentPack Selection Diagnosis", ""]
    if diagnosis.get("task"):
        lines.append(f"- Task: {diagnosis['task']}")
    lines.append(f"- Context: {diagnosis.get('context_path') or 'unknown'}")
    lines.append(f"- Selected files: {diagnosis['selected_count']}")
    lines.append("")
    lines.append("## Actions")
    for action in diagnosis["actions"]:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("## Largest Token Consumers")
    for item in diagnosis["largest_token_consumers"]:
        lines.append(f"- `{item['path']}` ({item['mode']}, {item['tokens']} tokens)")
    return "\n".join(lines).rstrip() + "\n"
