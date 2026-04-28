from __future__ import annotations

import typer
from rich.table import Table

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def diff() -> None:
        """Show changes since last snapshot."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        files = scan(root, ignore_spec, cfg.context.max_file_tokens)
        current = build_snapshot(files)
        previous = load_snapshot(root)
        result = diff_snapshots(previous, current)

        table = Table(title="Snapshot Diff", show_header=True)
        table.add_column("Category", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Added files", str(len(result.added)))
        table.add_row("Modified files", str(len(result.modified)))
        table.add_row("Deleted files", str(len(result.deleted)))
        table.add_row("Unchanged files", str(len(result.unchanged)))
        console.print(table)

        for label, items, style in [
            ("Added", result.added, "green"),
            ("Modified", result.modified, "yellow"),
            ("Deleted", result.deleted, "red"),
        ]:
            if items:
                console.print(f"\n[{style}]{label}:[/]")
                for f in items[:30]:
                    console.print(f"  {f}")
                if len(items) > 30:
                    console.print(f"  ... and {len(items) - 30} more")
