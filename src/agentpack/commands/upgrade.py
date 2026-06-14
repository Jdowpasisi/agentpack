from __future__ import annotations

import typer

from agentpack.commands._shared import console, _root
from agentpack.commands.install import _install_slash_command, _print_install_results
from agentpack.integrations.agents import SUPPORTED_AGENTS, expand_agents, install_agent_integration


def register(app: typer.Typer) -> None:
    @app.command()
    def upgrade(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Agent integration to refresh after package upgrade ({' | '.join(SUPPORTED_AGENTS)}).",
        ),
    ) -> None:
        """Refresh the detected AgentPack IDE/agent integration after upgrading the package."""
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

        console.print("\n[bold green]Upgrade integration refresh complete.[/]")
