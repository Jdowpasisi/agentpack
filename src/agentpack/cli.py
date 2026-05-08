from __future__ import annotations

import typer
from agentpack.commands import init, scan, diff, status, stats, summarize, pack, install, monitor, explain, doctor, watch, claude_cmd, benchmark, mcp_cmd
from agentpack import __version__


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


app = typer.Typer(help="AgentPack — token-aware context packing for AI coding agents.")


@app.callback()
def _main(
    version: bool = typer.Option(False, "--version", "-v", callback=_version_callback, is_eager=True, help="Show version and exit."),
) -> None:
    pass


for mod in [init, scan, diff, status, stats, summarize, pack, install, monitor, explain, doctor, watch, claude_cmd, benchmark, mcp_cmd]:
    mod.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
