from __future__ import annotations

import typer
from agentpack.commands import (
    benchmark,
    claude_cmd,
    ci_cmd,
    dev_check,
    diagnose_selection,
    diff,
    doctor,
    eval_cmd,
    explain,
    guard,
    hook_cmd,
    ignore_cmd,
    init,
    install,
    mcp_cmd,
    migrate,
    monitor,
    next_cmd,
    pack,
    quickstart,
    release_cmd,
    release_check,
    repair,
    route,
    scan,
    skills,
    state_cmd,
    start_cmd,
    stats,
    status,
    summarize,
    task_cmd,
    threads,
    tune,
    verify_wheel,
    watch,
    workflow_cmd,
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
    ignore_cmd,
    scan,
    diff,
    status,
    state_cmd,
    task_cmd,
    threads,
    stats,
    summarize,
    pack,
    install,
    repair,
    route,
    next_cmd,
    migrate,
    monitor,
    explain,
    guard,
    doctor,
    diagnose_selection,
    eval_cmd,
    tune,
    watch,
    claude_cmd,
    benchmark,
    ci_cmd,
    dev_check,
    verify_wheel,
    mcp_cmd,
    hook_cmd,
    quickstart,
    skills,
    release_check,
    release_cmd,
    start_cmd,
    workflow_cmd,
]:
    mod.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
