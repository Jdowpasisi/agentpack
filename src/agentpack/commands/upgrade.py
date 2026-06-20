from __future__ import annotations

import subprocess

import typer

from agentpack.commands._shared import console, _root
from agentpack.commands.install import (
    _install_slash_command,
    _print_global_template_results,
    _print_install_results,
)
from agentpack.integrations import global_install as global_hooks
from agentpack.integrations.agents import SUPPORTED_AGENTS, expand_agents, install_agent_integration


def register(app: typer.Typer) -> None:
    @app.command()
    def upgrade(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Agent integration to refresh after package upgrade ({' | '.join(SUPPORTED_AGENTS)}).",
        ),
        repair_existing_global_hooks: bool = typer.Option(
            True,
            "--repair-existing-global-hooks/--no-repair-existing-global-hooks",
            help="Refresh already-installed global git/shell hooks after upgrading AgentPack.",
        ),
    ) -> None:
        """Refresh existing AgentPack repo/global integration surfaces after a package upgrade."""
        root = _root()
        if agent not in SUPPORTED_AGENTS:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

        agents = expand_agents(agent, root)
        if agent == "auto":
            console.print(f"[dim]Auto-detected agent: {agents[0]}[/]")

        for selected in agents:
            console.print(f"\n[bold]{selected}[/]")
            results = install_agent_integration(
                root,
                selected,
                install_slash_command=_install_slash_command,
            )
            _print_install_results(selected, results)

        if repair_existing_global_hooks:
            _repair_existing_global_hooks()

        console.print("\n[bold green]Upgrade integration refresh complete.[/]")
        console.print(f"  Verify with: [bold]agentpack doctor --agent {agent}[/]")


def _repair_existing_global_hooks() -> None:
    repaired = False
    if _global_git_templates_are_installed():
        repaired = True
        console.print("\n[bold]Refreshing existing global git template hooks...[/]")
        hook_results = global_hooks.install_git_template_hooks()
        _print_global_template_results(hook_results)
        git_cfg_action = global_hooks.configure_git_template_dir(dry_run=False)
        console.print(f"[green]git config --global init.templateDir {git_cfg_action}.[/]")

    rc_file = global_hooks._detect_rc_file()
    if rc_file is not None and rc_file.exists() and global_hooks._SHELL_MARKER_START in rc_file.read_text(encoding="utf-8"):
        repaired = True
        console.print("\n[bold]Refreshing existing shell cd hook...[/]")
        action, path = global_hooks.install_shell_hook(rc_file)
        if path is not None:
            console.print(f"[green]{path} {action}.[/]")

    if not repaired:
        console.print("\n[dim]No existing global AgentPack hooks found to refresh.[/]")


def _global_git_templates_are_installed() -> bool:
    hooks_dir = global_hooks._GIT_TEMPLATE_DIR / "hooks"
    for name in global_hooks._HOOK_SCRIPTS:
        hook_path = hooks_dir / name
        if hook_path.exists() and global_hooks._AGENTPACK_MARKER in hook_path.read_text(encoding="utf-8"):
            return True
    try:
        result = subprocess.run(
            ["git", "config", "--global", "init.templateDir"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return result.stdout.strip() == str(global_hooks._GIT_TEMPLATE_DIR)
