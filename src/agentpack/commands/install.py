from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentpack.installers.claude import ClaudeInstaller
from agentpack.installers.codex import CodexInstaller
from agentpack.installers.cursor import CursorInstaller
from agentpack.installers.windsurf import WindsurfInstaller
from agentpack.integrations.global_install import (
    install_git_template_hooks,
    configure_git_template_dir,
    install_shell_hook,
    remove_git_template_hooks,
    remove_shell_hook,
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
            installer = ClaudeInstaller()
            action = installer.patch_claude_md(root)
            console.print(f"[green]CLAUDE.md {action}.[/]")

            hook_action = installer.patch_claude_settings(root, global_install)
            scope = "~/.claude/settings.json" if global_install else ".claude/settings.json"
            console.print(f"[green]{scope} {hook_action}.[/]")

            if slash_command:
                _install_slash_command(root, global_install)

        elif agent == "cursor":
            installer = CursorInstaller()
            rules_action = installer.patch_cursor_rules(root)
            console.print(f"[green].cursorrules {rules_action}.[/]")
            mdc_action = installer.patch_cursor_mdc(root)
            console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")
            _print_auto_repack_results(installer.install_auto_repack(root))
            console.print("  Run [bold]agentpack pack --agent cursor --task \"<task>\"[/] to generate context.")

        elif agent == "windsurf":
            installer = WindsurfInstaller()
            rules_action = installer.patch_windsurfrules(root)
            console.print(f"[green].windsurfrules {rules_action}.[/]")
            _print_auto_repack_results(installer.install_auto_repack(root))
            console.print("  Run [bold]agentpack pack --agent windsurf --task \"<task>\"[/] to generate context.")

        elif agent == "codex":
            installer = CodexInstaller()
            action = installer.patch_agents_md(root)
            console.print(f"[green]AGENTS.md {action}.[/]")
            _print_auto_repack_results(installer.install_auto_repack(root))
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
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be changed without mutating anything."),
    ) -> None:
        """Install agentpack once — works in every repo from that point on.

        Sets up git template hooks (fired on every git init/clone) and a shell
        cd hook so agentpack auto-bootstraps silently whenever you enter a git
        repo for the first time. No per-project setup required after this.
        """
        import subprocess as sp

        if dry_run:
            console.print("[bold yellow]Dry run — no files will be changed.[/]\n")

        if pipx and not dry_run:
            console.print("[bold]Installing agentpack globally via pipx...[/]")
            result = sp.run(
                ["pipx", "install", "agentpack-cli", "--force"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                console.print("[green]agentpack installed globally.[/] Available as `agentpack` in any shell.")
            else:
                console.print("[yellow]pipx install failed. Trying pip install --user...[/]")
                result2 = sp.run(
                    [sys.executable, "-m", "pip", "install", "--user", "agentpack-cli"],
                    capture_output=True, text=True,
                )
                if result2.returncode != 0:
                    console.print(f"[red]Install failed:[/] {result2.stderr[:200]}")
                    raise typer.Exit(1)
                console.print("[green]Installed via pip --user.[/]")
        elif pipx and dry_run:
            console.print("[dim]Would run: pipx install agentpack-cli[/]")

        # --- Git template hooks (fire on every future git init / clone) ---
        if git_template:
            console.print("\n[bold]Git template hooks:[/]" if dry_run else "\n[bold]Setting up git template hooks...[/]")
            hook_results = install_git_template_hooks(dry_run=dry_run)
            for name, action in hook_results.items():
                if action != "unchanged":
                    prefix = "[dim]" if dry_run else "[green]"
                    suffix = "[/]"
                    console.print(f"{prefix}~/.git-templates/hooks/{name} {action}.{suffix}")
            git_cfg_action = configure_git_template_dir(dry_run=dry_run)
            console.print(f"[dim]git config --global init.templateDir {git_cfg_action}.[/]" if dry_run
                          else f"[green]git config --global init.templateDir {git_cfg_action}.[/]")
            if not dry_run:
                console.print("  Every future [bold]git init[/] or [bold]git clone[/] will auto-bootstrap agentpack.")

        # --- Shell cd hook (fires when entering opted-in repos) ---
        if shell_hook:
            console.print("\n[bold]Shell cd hook:[/]" if dry_run else "\n[bold]Setting up shell cd hook...[/]")
            action, rc_path = install_shell_hook(dry_run=dry_run)
            if rc_path:
                prefix = "[dim]" if dry_run else "[green]"
                console.print(f"{prefix}{rc_path} {action}.[/]")
                if not dry_run:
                    console.print("  When you [bold]cd[/] into a repo with [dim].agentpack/config.toml[/], agentpack")
                    console.print("  silently repacks if stale. [dim]Non-configured repos are never touched.[/]")
                    console.print(f"  [dim]Reload with: source {rc_path}[/]")
            else:
                console.print(f"[yellow]Shell hook: {action}[/]")

        root = _root()

        # --- Agent-specific config ---
        if agent == "claude":
            if not dry_run:
                hook_action = ClaudeInstaller().patch_claude_settings(root, global_install=True)
                console.print(f"\n[green]~/.claude/settings.json {hook_action}.[/]")
                _install_slash_command(root, global_install=True)
            else:
                console.print("\n[dim]Would patch: ~/.claude/settings.json (hooks)[/]")
                console.print("[dim]Would install: ~/.claude/commands/agentpack.md (slash command)[/]")

        elif agent == "cursor":
            if not dry_run:
                inst = CursorInstaller()
                rules_action = inst.patch_cursor_rules(root)
                console.print(f"\n[green].cursorrules {rules_action}.[/]")
                mdc_action = inst.patch_cursor_mdc(root)
                console.print(f"[green].cursor/rules/agentpack.mdc {mdc_action}.[/]")
            else:
                console.print("\n[dim]Would patch: .cursorrules, .cursor/rules/agentpack.mdc[/]")

        elif agent == "windsurf":
            if not dry_run:
                rules_action = WindsurfInstaller().patch_windsurfrules(root)
                console.print(f"\n[green].windsurfrules {rules_action}.[/]")
            else:
                console.print("\n[dim]Would patch: .windsurfrules[/]")

        elif agent == "codex":
            if not dry_run:
                action = CodexInstaller().patch_agents_md(root)
                console.print(f"\n[green]AGENTS.md {action}.[/]")
            else:
                console.print("\n[dim]Would patch: AGENTS.md[/]")

        else:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

        if dry_run:
            console.print("\n[bold yellow]Dry run complete. Re-run without --dry-run to apply.[/]")
        else:
            console.print("\n[bold green]Global install complete.[/]")
            console.print("  Git hooks fire on commit/merge/checkout — [bold]only in opted-in repos[/].")
            if shell_hook:
                console.print("  Shell hook repacks on cd — [bold]only in repos with .agentpack/config.toml[/].")
            console.print("  To opt a repo in: [bold]cd repo && agentpack init[/]")

    @app.command(name="global-uninstall")
    def global_uninstall_cmd(
        shell_hook: bool = typer.Option(True, "--shell-hook/--no-shell-hook", help="Remove cd hook from shell rc."),
        git_template: bool = typer.Option(True, "--git-template/--no-git-template", help="Remove git template hooks."),
    ) -> None:
        """Remove agentpack global hooks (git templates + shell rc hook).

        Per-project .agentpack/ directories and agent config files are not touched.
        """
        if git_template:
            console.print("[bold]Removing git template hooks...[/]")
            results = remove_git_template_hooks()
            if results:
                for name, action in results.items():
                    if action != "unchanged":
                        console.print(f"[green]~/.git-templates/hooks/{name} {action}.[/]")
            else:
                console.print("[dim]No git template hooks found.[/]")

        if shell_hook:
            console.print("\n[bold]Removing shell cd hook...[/]")
            action, rc_path = remove_shell_hook()
            if rc_path:
                console.print(f"[green]{rc_path} {action}.[/]")
            else:
                console.print("[dim]No shell hook found (unknown shell).[/]")

        console.print("\n[bold green]Global uninstall complete.[/]")
        console.print("  Per-project [dim].agentpack/[/] directories are untouched.")
        console.print("  To remove from a specific repo: delete [dim].agentpack/[/] and remove agent config.")


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
