from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentpack.adapters.claude import ClaudeAdapter
from agentpack.adapters.codex import CodexAdapter
from agentpack.adapters.cursor import CursorAdapter
from agentpack.adapters.windsurf import WindsurfAdapter
from agentpack.commands._shared import console, _root

_SUPPORTED_AGENTS = ("claude", "cursor", "windsurf", "codex")


def register(app: typer.Typer) -> None:
    @app.command()
    def install(
        agent: str = typer.Option("claude", "--agent", help=f"Target agent ({' | '.join(_SUPPORTED_AGENTS)})."),
        slash_command: bool = typer.Option(True, "--slash-command/--no-slash-command", help="Install /agentpack slash command (Claude only)."),
        global_install: bool = typer.Option(False, "--global/--local", help="Install globally or locally."),
    ) -> None:
        """Configure agentpack for your AI coding agent (Claude, Cursor, or Windsurf)."""
        root = _root()

        if agent == "claude":
            adapter = ClaudeAdapter()
            action = adapter.patch_claude_md(root)
            console.print(f"[green]CLAUDE.md {action}.[/]")

            hook_action = adapter.patch_claude_settings(root, global_install)
            scope = "~/.claude/settings.json" if global_install else ".claude/settings.json"
            console.print(f"[green]{scope} {hook_action}.[/]")

            if slash_command:
                _install_slash_command(root, global_install)

        elif agent == "cursor":
            adapter = CursorAdapter()
            # Write .cursorrules (legacy + v0.43+ .mdc)
            rules_action = adapter.patch_cursor_rules(root)
            console.print(f"[green].cursorrules {rules_action}.[/]")
            mdc_action = adapter.patch_cursor_mdc(root)
            console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")
            console.print("  Cursor will read [bold].agentpack/context.md[/] automatically.")
            console.print("  Run [bold]agentpack pack --agent cursor --task \"<task>\"[/] to generate context.")

        elif agent == "windsurf":
            adapter = WindsurfAdapter()
            rules_action = adapter.patch_windsurfrules(root)
            console.print(f"[green].windsurfrules {rules_action}.[/]")
            console.print("  Windsurf will read [bold].agentpack/context.md[/] automatically.")
            console.print("  Run [bold]agentpack pack --agent windsurf --task \"<task>\"[/] to generate context.")

        elif agent == "codex":
            adapter = CodexAdapter()
            action = adapter.patch_agents_md(root)
            console.print(f"[green]AGENTS.md {action}.[/]")
            console.print("  Codex will read [bold].agentpack/context.md[/] at the start of each task.")
            console.print("  Run [bold]agentpack pack --agent codex --task \"<task>\"[/] to generate context.")

        else:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

    @app.command(name="global-install")
    def global_install_cmd(
        agent: str = typer.Option("claude", "--agent", help=f"Target agent ({' | '.join(_SUPPORTED_AGENTS)})."),
        pipx: bool = typer.Option(True, "--pipx/--no-pipx", help="Install via pipx for global availability."),
    ) -> None:
        """Install agentpack globally (pipx) and configure the target agent system-wide."""
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

        root = _root()

        if agent == "claude":
            adapter = ClaudeAdapter()
            hook_action = adapter.patch_claude_settings(root, global_install=True)
            console.print(f"[green]~/.claude/settings.json {hook_action}.[/]")
            _install_slash_command(root, global_install=True)
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  `agentpack` is available in any terminal.")
            console.print("  `/agentpack` is available in any Claude CLI session.")

        elif agent == "cursor":
            adapter = CursorAdapter()
            rules_action = adapter.patch_cursor_rules(root)
            console.print(f"[green].cursorrules {rules_action}.[/]")
            mdc_action = adapter.patch_cursor_mdc(root)
            console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  Run [bold]agentpack install --agent cursor[/] in each project.")

        elif agent == "windsurf":
            adapter = WindsurfAdapter()
            rules_action = adapter.patch_windsurfrules(root)
            console.print(f"[green].windsurfrules {rules_action}.[/]")
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  Run [bold]agentpack install --agent windsurf[/] in each project.")

        elif agent == "codex":
            adapter = CodexAdapter()
            action = adapter.patch_agents_md(root)
            console.print(f"[green]AGENTS.md {action}.[/]")
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  Run [bold]agentpack install --agent codex[/] in each project.")

        else:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)


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
