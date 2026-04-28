from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentpack.adapters.claude import ClaudeAdapter
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def install(
        agent: str = typer.Option("claude", "--agent", help="Target agent."),
        slash_command: bool = typer.Option(True, "--slash-command/--no-slash-command", help="Install /agentpack slash command."),
        global_install: bool = typer.Option(False, "--global/--local", help="Install globally (~/.claude/commands/) or locally (.claude/commands/)."),
    ) -> None:
        """Patch CLAUDE.md and install the /agentpack slash command for Claude CLI."""
        root = _root()

        if agent == "claude":
            adapter = ClaudeAdapter()
            action = adapter.patch_claude_md(root)
            console.print(f"[green]CLAUDE.md {action}.[/]")

            if slash_command:
                _install_slash_command(root, global_install)
        else:
            console.print(f"[yellow]No install action defined for agent: {agent}[/]")

    @app.command(name="global-install")
    def global_install_cmd(
        agent: str = typer.Option("claude", "--agent", help="Target agent."),
        pipx: bool = typer.Option(True, "--pipx/--no-pipx", help="Install via pipx for global availability."),
    ) -> None:
        """Install agentpack globally (pipx) and set up the slash command system-wide."""
        import subprocess as sp

        if pipx:
            console.print("[bold]Installing agentpack globally via pipx...[/]")
            result = sp.run(
                ["pipx", "install", "agentpack", "--force"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                console.print("[green]agentpack installed globally.[/] Available as `agentpack` in any shell.")
            else:
                console.print("[yellow]pipx install failed. Trying pip install --user...[/]")
                result2 = sp.run(
                    [sys.executable, "-m", "pip", "install", "--user", "agentpack"],
                    capture_output=True, text=True,
                )
                if result2.returncode != 0:
                    console.print(f"[red]Install failed:[/] {result2.stderr[:200]}")
                    raise typer.Exit(1)
                console.print("[green]Installed via pip --user.[/]")

        # Install slash command globally
        if agent == "claude":
            root = _root()
            _install_slash_command(root, global_install=True)
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  `agentpack` is available in any terminal.")
            console.print("  `/agentpack` is available in any Claude CLI session.")
        else:
            console.print(f"[yellow]No slash command defined for agent: {agent}[/]")


def _install_slash_command(root: Path, global_install: bool) -> None:
    import importlib.resources

    commands_dir = (
        Path.home() / ".claude" / "commands" if global_install
        else root / ".claude" / "commands"
    )
    commands_dir.mkdir(parents=True, exist_ok=True)
    dest = commands_dir / "agentpack.md"

    try:
        pkg_files = importlib.resources.files("agentpack") / "data" / "agentpack.md"
        source_text = pkg_files.read_text(encoding="utf-8")
    except Exception:
        source_text = (Path(__file__).parent.parent / "data" / "agentpack.md").read_text()

    dest.write_text(source_text)
    scope = "global" if global_install else "local"
    console.print(f"[green]Slash command installed ({scope}):[/] {dest}")
    console.print("  Use [bold]/agentpack[/] in any Claude CLI session.")
