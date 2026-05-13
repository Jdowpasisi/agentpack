from __future__ import annotations

import typer
from rich.table import Table

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.application.pack_service import AdapterRegistry
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command(name="scan")
    def scan_cmd() -> None:
        """Scan the repository and report file statistics."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        console.print("[bold]Scanning repository...[/]")
        scan_result = scan(
            root,
            ignore_spec,
            cfg.context.max_file_tokens,
            always_skip_paths=AdapterRegistry.generated_output_paths(root, cfg),
        )

        total = len(scan_result.all_files)
        ignored = len(scan_result.ignored) + len(scan_result.binary)
        scanned = len(scan_result.packable)
        raw_tokens = sum(f.estimated_tokens for f in scan_result.all_files)
        after_ignore = sum(f.estimated_tokens for f in scan_result.packable)

        largest = sorted(
            scan_result.packable,
            key=lambda x: x.estimated_tokens,
            reverse=True,
        )[:10]

        table = Table(title="Repository Scan", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Files discovered", str(total))
        table.add_row("Files ignored / binary", str(ignored))
        table.add_row("Files scanned", str(scanned))
        table.add_row("Raw estimated tokens", f"{raw_tokens:,}")
        table.add_row("Tokens after ignore", f"{after_ignore:,}")
        console.print(table)

        if largest:
            lt = Table(title="Largest Files", show_header=True)
            lt.add_column("File", style="dim")
            lt.add_column("Tokens", justify="right")
            for f in largest:
                lt.add_row(f.path, f"{f.estimated_tokens:,}")
            console.print(lt)
