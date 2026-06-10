from __future__ import annotations

import json

import typer

from agentpack.commands._shared import console, _root, run_refresh
from agentpack.commands.diagnose_selection import build_selection_diagnosis, _markdown_report
from agentpack.commands.guard import _context_is_fresh
from agentpack.core.config import load_config
from agentpack.core.context_pack import load_pack_metadata
from agentpack.core.loop_protocol import load_loop_state
from agentpack.core.thread_context import detect_conflicts, list_thread_rows
from agentpack.integrations.platform import cli_module_argv
from agentpack.session.state import TASK_FILE
import subprocess


def register(app: typer.Typer) -> None:
    @app.command("next")
    def next_action(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
        fix: bool = typer.Option(False, "--fix", help="Refresh stale context when safe."),
        fix_all_safe: bool = typer.Option(False, "--fix-all-safe", help="Run all safe repairs AgentPack can do without deleting or applying ignore suggestions."),
    ) -> None:
        """Recommend the next AgentPack action for this repo."""
        root = _root()
        recommendations = _recommendations(root)
        fixes: list[dict[str, str | int]] = []
        if fix_all_safe:
            recommendations, fixes = _fix_all_safe(root, recommendations)
        if fix and any(item["kind"] == "stale_context" for item in recommendations):
            stats = run_refresh(root, "auto", "balanced", 0)
            if stats:
                recommendations = [{"kind": "fixed", "command": "agentpack next", "reason": "refreshed stale context"}]
                fixes.append({"kind": "stale_context", "command": "agentpack guard --agent auto --repair-stale --refresh-context", "returncode": 0})
        payload = {"recommendations": recommendations, "fixes": fixes, "ok": not recommendations}
        if json_output:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
            return
        if not recommendations:
            console.print("[green]✓[/] No obvious AgentPack action required.")
            return
        for item in recommendations:
            console.print(f"[bold]{item['command']}[/]")
            console.print(f"  [dim]{item['reason']}[/]")
        for item in fixes:
            marker = "[green]✓[/]" if item.get("returncode") == 0 else "[red]✗[/]"
            console.print(f"{marker} fixed {item['kind']}: [dim]{item['command']}[/]")


def _recommendations(root) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not (root / ".agentpack" / "config.toml").exists():
        return [{"kind": "init", "command": "agentpack init --yes", "reason": "repo is not initialized"}]
    if not _has_task(root):
        items.append({"kind": "missing_task", "command": 'agentpack start "describe the task"', "reason": "no concrete task is set"})
    fresh, reason = _context_is_fresh(root)
    if not fresh:
        items.append({"kind": "stale_context", "command": "agentpack guard --agent auto --repair-stale --refresh-context", "reason": reason})
    if _has_thread_conflicts(root):
        items.append({"kind": "thread_conflict", "command": "agentpack threads --conflicts", "reason": "active threads overlap on this branch/worktree"})
    if _pack_looks_noisy(root):
        items.append({"kind": "selection_noise", "command": "agentpack diagnose-selection", "reason": "latest pack has broad/noisy selection signals"})
    items.extend(_loop_recommendations(root))
    return items


def _has_task(root) -> bool:
    path = root / TASK_FILE
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8").strip()
    return bool(text and "Write or update the current coding task here." not in text)


def _has_thread_conflicts(root) -> bool:
    rows = list_thread_rows(root, active_only=True)
    return any(detect_conflicts(root, row).get("conflicts") for row in rows)


def _pack_looks_noisy(root) -> bool:
    meta = load_pack_metadata(root) or {}
    freshness = meta.get("freshness") or {}
    selected = meta.get("selected_files_meta") or []
    if freshness.get("generic_task_ratio", 0) and float(freshness.get("generic_task_ratio") or 0) >= 0.5:
        return True
    if freshness.get("mode_warning"):
        return True
    if isinstance(selected, list) and selected:
        summary_count = sum(1 for item in selected if isinstance(item, dict) and item.get("mode") == "summary")
        return summary_count / len(selected) >= 0.7
    return False


def _loop_recommendations(root) -> list[dict[str, str]]:
    cfg = load_config(root)
    if not cfg.loop.enabled:
        return []
    state = load_loop_state(root)
    if state is None:
        return []
    if not state.runner:
        return [{"kind": "loop_runner_missing", "command": 'agentpack work "..." --run --runner "..."', "reason": "Ralph Loop state exists but no runner is configured"}]
    if state.status == "ready_to_finish":
        return [{"kind": "loop_ready_to_finish", "command": "agentpack finish --since main", "reason": "Ralph Loop verification passed"}]
    if state.status == "blocked":
        return [{"kind": "loop_blocked", "command": "agentpack dashboard", "reason": f"Ralph Loop blocked: {state.blocked_reason or 'inspect loop failures'}"}]
    return [{"kind": "loop_continue", "command": f'agentpack work "{state.task}" --run', "reason": f"Ralph Loop is {state.status}"}]


def _fix_all_safe(root, recommendations: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
    fixes: list[dict[str, str | int]] = []
    if any(item["kind"] == "init" for item in recommendations):
        result = subprocess.run(cli_module_argv("init", "--yes"), cwd=root, capture_output=True, text=True)
        fixes.append({"kind": "init", "command": "agentpack init --yes", "returncode": result.returncode})
        if result.returncode != 0:
            return recommendations, fixes
        recommendations = _recommendations(root)
    if any(item["kind"] == "stale_context" for item in recommendations):
        stats = run_refresh(root, "auto", "balanced", 0)
        fixes.append({
            "kind": "stale_context",
            "command": "agentpack guard --agent auto --repair-stale --refresh-context",
            "returncode": 0 if stats else 1,
        })
        recommendations = _recommendations(root)
    if any(item["kind"] == "selection_noise" for item in recommendations):
        diagnosis = build_selection_diagnosis(root)
        out = root / ".agentpack" / "selection_diagnosis.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_markdown_report(diagnosis), encoding="utf-8")
        fixes.append({"kind": "selection_noise", "command": "agentpack diagnose-selection --write", "returncode": 0})
        recommendations = [item for item in recommendations if item["kind"] != "selection_noise"]
    return recommendations, fixes
