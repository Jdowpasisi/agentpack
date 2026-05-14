from __future__ import annotations

import typer

from agentpack.commands._shared import console, _root
from agentpack.commands.install import _install_slash_command, _print_install_results
from agentpack.integrations.agents import SUPPORTED_AGENTS, expand_agents, install_agent_integration


def register(app: typer.Typer) -> None:
    @app.command()
    def repair(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Agent to repair ({' | '.join(SUPPORTED_AGENTS)}). Use all to repair every integration.",
        ),
        global_install: bool = typer.Option(False, "--global/--local", help="Repair global agent config where supported."),
    ) -> None:
        """Repair missing or drifted AgentPack integration files."""
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
                global_install=global_install,
                install_slash_command=_install_slash_command,
            )
            _print_install_results(selected, results)

        console.print("\n[bold green]Repair complete.[/]")
