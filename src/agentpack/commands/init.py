from __future__ import annotations

import sys
from typing import Optional

import typer

from agentpack.core.config import DEFAULT_CONFIG, save_config
from agentpack.core.ignore import DEFAULT_AGENTIGNORE
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def init(
        force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
        mode: Optional[str] = typer.Option(None, "--mode", help="Default pack mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Default token budget (0 = keep default 25000)."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive prompts, use defaults."),
        share_cache: bool = typer.Option(False, "--share-cache", help="Commit summary cache to git (recommended for teams)."),
    ) -> None:
        """Initialize AgentPack in the current directory."""
        root = _root()
        agentpack_dir = root / ".agentpack"
        agentpack_dir.mkdir(exist_ok=True)
        (agentpack_dir / "snapshots").mkdir(exist_ok=True)
        (agentpack_dir / "cache").mkdir(exist_ok=True)

        gitignore = agentpack_dir / ".gitignore"
        if not gitignore.exists() or force:
            # With --share-cache, cache/ is committed so teammates skip the summarize step
            cache_line = "" if share_cache else ".agentpack/cache/\n"
            gitignore.write_text(
                f"{cache_line}.agentpack/snapshots/\n.agentpack/context.*\n.agentpack/metrics.jsonl\n"
            )
            console.print("[green]Created[/] .agentpack/.gitignore")
            if share_cache:
                console.print("  [dim]cache/ not gitignored — commit it so teammates skip agentpack summarize[/]")
        else:
            console.print("[dim]Skipped[/] .agentpack/.gitignore (exists)")

        config_path_file = agentpack_dir / "config.toml"
        if not config_path_file.exists() or force:
            cfg = DEFAULT_CONFIG.model_copy(deep=True)

            # Interactive mode selection
            if not yes and mode is None and sys.stdin.isatty():
                console.print("\n[bold]Choose default pack mode:[/]")
                console.print("  [cyan]1[/] minimal  — changed files + configs only (fastest, fewest tokens)")
                console.print("  [cyan]2[/] balanced — + deps, tests, summaries [bold](recommended)[/]")
                console.print("  [cyan]3[/] deep     — + docs, more full files (most context)")
                choice = typer.prompt("Mode", default="2")
                mode_map = {"1": "minimal", "2": "balanced", "3": "deep",
                            "minimal": "minimal", "balanced": "balanced", "deep": "deep"}
                cfg.context.default_mode = mode_map.get(choice.strip(), "balanced")
            elif mode in ("minimal", "balanced", "deep"):
                cfg.context.default_mode = mode

            if budget > 0:
                cfg.context.default_budget = budget

            save_config(cfg, root)
            console.print(f"[green]Created[/] .agentpack/config.toml  [dim](mode: {cfg.context.default_mode}, budget: {cfg.context.default_budget:,})[/]")
        else:
            console.print("[dim]Skipped[/] .agentpack/config.toml (exists)")

        ignore_path = root / ".agentignore"
        if not ignore_path.exists() or force:
            ignore_path.write_text(DEFAULT_AGENTIGNORE)
            console.print("[green]Created[/] .agentignore")
        else:
            console.print("[dim]Skipped[/] .agentignore (exists)")

        console.print("\n[bold green]AgentPack initialized.[/]")
        console.print("Run [bold]agentpack scan[/] to explore your repo.")
