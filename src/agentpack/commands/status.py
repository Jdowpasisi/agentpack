from __future__ import annotations

import typer

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot
from agentpack.core.context_pack import load_pack_metadata
from agentpack.commands._shared import console, _root


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

        files = scan(root, ignore_spec, cfg.context.max_file_tokens)
        current = build_snapshot(files)

        if current["root_hash"] == meta.get("snapshot_root_hash"):
            console.print("[green]Context pack is up to date.[/]")
            console.print(f"  Task: {meta.get('task')}")
            console.print(f"  Generated: {meta.get('generated_at')}")
        else:
            console.print("[yellow]Context pack is STALE.[/] Files changed since last pack.")
            console.print(f"  Last generated: {meta.get('generated_at')}")
            console.print("  Run [bold]agentpack pack[/] to refresh.")
            raise typer.Exit(1)
