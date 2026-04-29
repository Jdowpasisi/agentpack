from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentpack.adapters.claude import ClaudeAdapter
from agentpack.adapters.codex import CodexAdapter
from agentpack.adapters.cursor import CursorAdapter
from agentpack.adapters.windsurf import WindsurfAdapter
from agentpack.core.global_install import (
    install_git_template_hooks,
    configure_git_template_dir,
    install_shell_hook,
)
from agentpack.commands._shared import console, _root

_SUPPORTED_AGENTS = ("claude", "cursor", "windsurf", "codex")


def register(app: typer.Typer) -> None:
    @app.command()
    def install(
        agent: str = typer.Option("claude", "--agent", help=f"Target agent ({' | '.join(_SUPPORTED_AGENTS)})."),
        slash_command: bool = typer.Option(True, "--slash-command/--no-slash-command", help="Install /agentpack slash command (Claude only)."),
        global_install: bool = typer.Option(False, "--global/--local", help="Install globally or locally."),
    ) -> None:
        """Configure agentpack for your AI coding agent (Claude, Cursor, Windsurf, or Codex)."""
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
            rules_action = adapter.patch_cursor_rules(root)
            console.print(f"[green].cursorrules {rules_action}.[/]")
            mdc_action = adapter.patch_cursor_mdc(root)
            console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")
            _print_auto_repack_results(adapter.install_auto_repack(root))
            console.print("  Run [bold]agentpack pack --agent cursor --task \"<task>\"[/] to generate context.")

        elif agent == "windsurf":
            adapter = WindsurfAdapter()
            rules_action = adapter.patch_windsurfrules(root)
            console.print(f"[green].windsurfrules {rules_action}.[/]")
            _print_auto_repack_results(adapter.install_auto_repack(root))
            console.print("  Run [bold]agentpack pack --agent windsurf --task \"<task>\"[/] to generate context.")

        elif agent == "codex":
            adapter = CodexAdapter()
            action = adapter.patch_agents_md(root)
            console.print(f"[green]AGENTS.md {action}.[/]")
            _print_auto_repack_results(adapter.install_auto_repack(root))
            console.print("  Run [bold]agentpack pack --agent codex --task \"<task>\"[/] to generate context.")

        else:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

    @app.command(name="global-install")
    def global_install_cmd(
        agent: str = typer.Option("claude", "--agent", help=f"Target agent ({' | '.join(_SUPPORTED_AGENTS)})."),
        pipx: bool = typer.Option(True, "--pipx/--no-pipx", help="Install via pipx for global availability."),
        shell_hook: bool = typer.Option(True, "--shell-hook/--no-shell-hook", help="Add cd hook to shell rc for auto-bootstrap."),
        git_template: bool = typer.Option(True, "--git-template/--no-git-template", help="Install git template hooks for every new repo."),
    ) -> None:
        """Install agentpack once — works in every repo from that point on.

        Sets up git template hooks (fired on every git init/clone) and a shell
        cd hook so agentpack auto-bootstraps silently whenever you enter a git
        repo for the first time. No per-project setup required after this.
        """
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

        # --- Git template hooks (fire on every future git init / clone) ---
        if git_template:
            console.print("\n[bold]Setting up git template hooks...[/]")
            hook_results = install_git_template_hooks()
            for name, action in hook_results.items():
                if action != "unchanged":
                    console.print(f"[green]~/.git-templates/hooks/{name} {action}.[/]")
            git_cfg_action = configure_git_template_dir()
            console.print(f"[green]git config --global init.templateDir {git_cfg_action}.[/]")
            console.print("  Every future [bold]git init[/] or [bold]git clone[/] will auto-bootstrap agentpack.")

        # --- Shell cd hook (fires when entering opted-in repos) ---
        if shell_hook:
            console.print("\n[bold]Setting up shell cd hook...[/]")
            action, rc_path = install_shell_hook()
            if rc_path:
                console.print(f"[green]{rc_path} {action}.[/]")
                console.print("  When you [bold]cd[/] into a repo with [dim].agentpack/config.toml[/], agentpack")
                console.print("  silently repacks if stale. [dim]Non-configured repos are never touched.[/]")
                console.print(f"  [dim]Reload with: source {rc_path}[/]")
            else:
                console.print(f"[yellow]Shell hook: {action}[/]")

        root = _root()

        # --- Agent-specific config ---
        if agent == "claude":
            adapter = ClaudeAdapter()
            hook_action = adapter.patch_claude_settings(root, global_install=True)
            console.print(f"\n[green]~/.claude/settings.json {hook_action}.[/]")
            _install_slash_command(root, global_install=True)

        elif agent == "cursor":
            adapter = CursorAdapter()
            rules_action = adapter.patch_cursor_rules(root)
            console.print(f"\n[green].cursorrules {rules_action}.[/]")
            mdc_action = adapter.patch_cursor_mdc(root)
            console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")

        elif agent == "windsurf":
            adapter = WindsurfAdapter()
            rules_action = adapter.patch_windsurfrules(root)
            console.print(f"\n[green].windsurfrules {rules_action}.[/]")

        elif agent == "codex":
            adapter = CodexAdapter()
            action = adapter.patch_agents_md(root)
            console.print(f"\n[green]AGENTS.md {action}.[/]")

        else:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

        console.print("\n[bold green]Global install complete.[/]")
        console.print("  Git hooks fire on commit/merge/checkout — [bold]only in opted-in repos[/].")
        if shell_hook:
            console.print("  Shell hook repacks on cd — [bold]only in repos with .agentpack/config.toml[/].")
        console.print("  To opt a repo in: [bold]cd repo && agentpack init[/]")


def _print_auto_repack_results(results: dict[str, str]) -> None:
    for key, action in results.items():
        if action == "unchanged":
            continue
        if key.startswith("git:"):
            console.print(f"[green].git/hooks/{key[4:]} {action}.[/]")
        elif key == "vscode:tasks":
            console.print(f"[green].vscode/tasks.json {action}.[/]")


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
