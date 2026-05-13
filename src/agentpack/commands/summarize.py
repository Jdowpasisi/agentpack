from __future__ import annotations

import typer

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.application.pack_service import AdapterRegistry
from agentpack.summaries.base import get_or_build_summary
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def summarize(
        refresh: bool = typer.Option(False, "--refresh", help="Force rebuild all summaries."),
    ) -> None:
        """Build or refresh offline summary cache (no API calls)."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        console.print("[bold]Building offline summaries...[/]")

        scan_result = scan(
            root,
            ignore_spec,
            cfg.context.max_file_tokens,
            always_skip_paths=AdapterRegistry.generated_output_paths(root, cfg),
        )
        active = scan_result.packable

        if refresh:
            from agentpack.core import cache as summary_cache
            for fi in active:
                if fi.hash:
                    cache_path = (
                        root / ".agentpack" / "cache" /
                        f"{summary_cache._cache_key(fi.path, fi.hash, 'offline', 1)}.json"
                    )
                    cache_path.unlink(missing_ok=True)

        built = 0
        errors = 0
        for fi in active:
            try:
                get_or_build_summary(fi, root)
                built += 1
            except Exception as e:
                console.print(f"[yellow]Warning:[/] {fi.path}: {e}")
                errors += 1

        console.print(f"[green]Done.[/] Built/refreshed {built} summaries.", end="")
        if errors:
            console.print(f" [yellow]{errors} errors.[/]")
        else:
            console.print()
