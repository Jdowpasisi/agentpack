from __future__ import annotations

from typing import Optional

import typer

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.summaries.base import get_or_build_summary
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def summarize(
        provider: str = typer.Option("offline", "--provider", help="Summary provider (offline|claude)."),
        refresh: bool = typer.Option(False, "--refresh", help="Force rebuild all summaries."),
        model: Optional[str] = typer.Option(None, "--model", help="LLM model override (for claude provider)."),
    ) -> None:
        """Build or refresh summary cache. Default: offline (no API calls)."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        if provider not in ("offline", "claude"):
            console.print("[red]Supported providers: offline, claude[/]")
            raise typer.Exit(1)

        if provider == "claude":
            console.print("[bold]Building LLM summaries via Claude (requires ANTHROPIC_API_KEY)...[/]")
        else:
            console.print("[bold]Building offline summaries...[/]")

        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        active = scan_result.packable

        built = 0
        errors = 0
        for fi in active:
            try:
                if provider == "claude" and model:
                    # pass model through via a thin wrapper
                    from agentpack.summaries import llm as llm_mod
                    from agentpack.core import cache as summary_cache
                    if fi.hash:
                        cached = summary_cache.load_summary(root, fi.path, fi.hash, provider)
                        if cached and not refresh:
                            built += 1
                            continue
                        summary = llm_mod.summarize(fi.path, fi.abs_path, fi.language, fi.hash or "", provider=provider, model=model)
                        summary_cache.save_summary(root, summary)
                else:
                    get_or_build_summary(fi, root, provider)
                built += 1
            except Exception as e:
                console.print(f"[yellow]Warning:[/] {fi.path}: {e}")
                errors += 1

        console.print(f"[green]Done.[/] Built/refreshed {built} summaries.", end="")
        if errors:
            console.print(f" [yellow]{errors} errors.[/]")
        else:
            console.print()
