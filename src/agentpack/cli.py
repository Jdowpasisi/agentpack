from __future__ import annotations

import typer
from agentpack.commands import (
    benchmark,
    claude_cmd,
    diff,
    doctor,
    explain,
    hook_cmd,
    init,
    install,
    mcp_cmd,
    monitor,
    pack,
    quickstart,
    repair,
    scan,
    stats,
    status,
    summarize,
    tune,
    watch,
)
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


for mod in [
    init,
    scan,
    diff,
    status,
    stats,
    summarize,
    pack,
    install,
    repair,
    monitor,
    explain,
    doctor,
    tune,
    watch,
    claude_cmd,
    benchmark,
    mcp_cmd,
    hook_cmd,
    quickstart,
]:
    mod.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
