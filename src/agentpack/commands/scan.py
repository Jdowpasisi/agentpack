from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.application.pack_service import AdapterRegistry
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command(name="scan")
    def scan_cmd(
        largest: int = typer.Option(10, "--largest", min=0, help="Show the N largest packable files by estimated tokens."),
        ignored_summary: bool = typer.Option(False, "--ignored-summary", help="Group ignored/binary files by directory or extension."),
    ) -> None:
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

        largest_files = sorted(
            scan_result.packable,
            key=lambda x: x.estimated_tokens,
            reverse=True,
        )[:largest]

        table = Table(title="Repository Scan", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Files discovered", str(total))
        table.add_row("Files ignored / binary", str(ignored))
        table.add_row("Files scanned", str(scanned))
        table.add_row("Raw estimated tokens", f"{raw_tokens:,}")
        table.add_row("Tokens after ignore", f"{after_ignore:,}")
        console.print(table)

        if largest_files:
            lt = Table(title="Largest Files", show_header=True)
            lt.add_column("File", style="dim")
            lt.add_column("Tokens", justify="right")
            for f in largest_files:
                lt.add_row(f.path, f"{f.estimated_tokens:,}")
            console.print(lt)

        if ignored_summary:
            ignored_rows = _ignored_summary(scan_result.ignored, scan_result.binary)
            if ignored_rows:
                it = Table(title="Ignored / Binary Summary", show_header=True)
                it.add_column("Bucket", style="dim")
                it.add_column("Files", justify="right")
                it.add_column("Bytes", justify="right")
                for bucket, count, size in ignored_rows:
                    it.add_row(bucket, f"{count:,}", f"{size:,}")
                console.print(it)


def _ignored_summary(ignored: list, binary: list, limit: int = 12) -> list[tuple[str, int, int]]:
    buckets: dict[str, tuple[int, int]] = {}
    for fi in [*ignored, *binary]:
        bucket = _ignore_bucket(fi.path)
        count, size = buckets.get(bucket, (0, 0))
        buckets[bucket] = (count + 1, size + int(getattr(fi, "size_bytes", 0) or 0))
    rows = [(bucket, count, size) for bucket, (count, size) in buckets.items()]
    rows.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return rows[:limit]


def _ignore_bucket(path: str) -> str:
    p = Path(path)
    first = p.parts[0] if p.parts else path
    if first.startswith("."):
        return first
    if first in {"node_modules", "vendor", "dist", "build", "coverage", "__pycache__"}:
        return first
    suffix = p.suffix.lower()
    if suffix:
        return f"*{suffix}"
    return first
