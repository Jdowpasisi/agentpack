from __future__ import annotations

import typer

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot
from agentpack.core.context_pack import load_pack_metadata
from agentpack.application.pack_service import AdapterRegistry
from agentpack.commands._shared import console, _root


def _task_md_body(root) -> str:
    path = root / ".agentpack" / "task.md"
    if not path.exists():
        return ""
    try:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    except OSError:
        return ""
    body = lines[0] if lines else ""
    if "Write or update the current coding task here." in body:
        return ""
    return body


def register(app: typer.Typer) -> None:
    @app.command()
    def status() -> None:
        """Check if the latest context pack is stale."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        meta = load_pack_metadata(root)
        if not meta:
            console.print("[yellow]No context pack found. Run agentpack pack to generate one.[/]")
            raise typer.Exit(1)

        scan_result = scan(
            root,
            ignore_spec,
            cfg.context.max_file_tokens,
            always_skip_paths=AdapterRegistry.generated_output_paths(root, cfg),
        )
        current = build_snapshot(scan_result.packable)

        task_md = _task_md_body(root)
        task_changed = bool(task_md and task_md != meta.get("task"))
        if current["root_hash"] == meta.get("snapshot_root_hash") and not task_changed:
            console.print("[green]Context pack is up to date.[/]")
            console.print(f"  Task: {meta.get('task')}")
            console.print(f"  Generated: {meta.get('generated_at')}")
        else:
            if task_changed:
                console.print("[yellow]Context pack is STALE.[/] .agentpack/task.md changed since last pack.")
                console.print(f"  Packed task: {meta.get('task')}")
                console.print(f"  Current task: {task_md}")
            else:
                console.print("[yellow]Context pack is STALE.[/] Files changed since last pack.")
            console.print(f"  Last generated: {meta.get('generated_at')}")
            console.print("  Run [bold]agentpack pack[/] to refresh.")
            raise typer.Exit(1)
