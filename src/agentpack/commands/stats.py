from __future__ import annotations

import typer
from rich.table import Table

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.context_pack import load_pack_metadata
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def stats() -> None:
        """Show token-saving statistics."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        meta = load_pack_metadata(root)

        raw = sum(f.estimated_tokens for f in scan_result.all_files)
        after_ignore = sum(f.estimated_tokens for f in scan_result.packable)
        packed = meta.get("token_estimate", 0) if meta else 0
        saving = (1 - packed / raw) * 100 if raw > 0 else 0

        ignored_count = len(scan_result.ignored) + len(scan_result.binary)
        included_count = 0
        summarized_count = 0

        if meta:
            context_path = root / meta.get("context_path", "")
            if context_path.exists():
                content = context_path.read_text()
                included_count = content.count("Included as: **full**")
                summarized_count = (
                    content.count("Included as: **summary**")
                    + content.count("Included as: **symbols**")
                )

        full_files = [f for f in scan_result.packable
                      if f.estimated_tokens <= cfg.context.max_file_tokens]
        manual_estimate = min(after_ignore, sum(f.estimated_tokens for f in full_files[:20]))
        vs_manual = (1 - packed / manual_estimate) * 100 if manual_estimate > 0 else 0

        table = Table(title="Token Stats", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Raw repo tokens", f"{raw:,}")
        table.add_row("After ignore", f"{after_ignore:,}")
        table.add_row("Packed tokens", f"[bold]{packed:,}[/]")
        table.add_row("vs. raw repo", f"[dim]{saving:.1f}% smaller[/]")
        table.add_row("vs. manual assembly (~20 files)", f"[green]{vs_manual:.1f}% smaller[/]")
        table.add_row("Files ignored", f"{ignored_count:,}")
        table.add_row("Files included (full)", f"{included_count:,}")
        table.add_row("Files summarized", f"{summarized_count:,}")
        console.print(table)
        console.print("[dim]'manual assembly' = hand-picking the 20 most relevant full files[/]")
