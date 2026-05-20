from __future__ import annotations

import typer
import shutil

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot
from agentpack.core.context_pack import load_pack_metadata
from agentpack.core.task_freshness import read_task_md, task_freshness
from agentpack.application.pack_service import AdapterRegistry
from agentpack.commands._shared import console, _root
from agentpack.integrations.agents import check_agent_integration, resolve_agent


def _task_md_body(root) -> str:
    return read_task_md(root) or ""


def register(app: typer.Typer) -> None:
    @app.command()
    def status(
        deep: bool = typer.Option(False, "--deep", help="Also show CLI, repo, task, and agent integration health."),
    ) -> None:
        """Check if the latest context pack is stale."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        meta = load_pack_metadata(root)
        if not meta:
            console.print("[yellow]No context pack found. Run agentpack pack to generate one.[/]")
            if deep:
                _print_deep_health(root, meta)
            raise typer.Exit(1)

        scan_result = scan(
            root,
            ignore_spec,
            cfg.context.max_file_tokens,
            always_skip_paths=AdapterRegistry.generated_output_paths(root, cfg),
        )
        current = build_snapshot(scan_result.packable)

        task_state = task_freshness(root, meta)
        task_md = task_state.current_task or ""
        task_changed = task_state.is_stale
        if current["root_hash"] == meta.get("snapshot_root_hash") and not task_changed:
            console.print("[green]Context pack is up to date.[/]")
            console.print(f"  Task: {meta.get('task')}")
            console.print(f"  Generated: {meta.get('generated_at')}")
            if deep:
                _print_deep_health(root, meta)
        else:
            if task_changed:
                console.print("[yellow]Context pack is STALE.[/] .agentpack/task.md changed since last pack.")
                console.print(f"  Packed task: {meta.get('task')}")
                console.print(f"  Current task: {task_md}")
                console.print("  AgentPack MCP `get_context()` will auto-refresh this mismatch.")
            else:
                console.print("[yellow]Context pack is STALE.[/] Files changed since last pack.")
            console.print(f"  Last generated: {meta.get('generated_at')}")
            console.print("  Run [bold]agentpack pack[/] to refresh.")
            if deep:
                _print_deep_health(root, meta)
            raise typer.Exit(1)


def _print_deep_health(root, meta: dict | None) -> None:
    console.print("\n[bold]Deep health[/]")
    binary = shutil.which("agentpack") or "(not on PATH)"
    console.print(f"  CLI: {binary}")
    console.print(f"  Repo: {root}")
    task = _task_md_body(root) or (meta or {}).get("task") or "(none)"
    console.print(f"  Task: {task}")
    try:
        agent = resolve_agent("auto", root)
    except Exception:
        agent = "generic"
    console.print(f"  Active agent: {agent}")
    for check in check_agent_integration(root, agent):
        marker = "[green]✓[/]" if check.ok else "[yellow]![/]"
        fix = f" — {check.fix}" if check.fix and not check.ok else ""
        console.print(f"  {marker} {check.label}: {check.detail}{fix}")
