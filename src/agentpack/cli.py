from __future__ import annotations

import typer
from agentpack.commands import init, scan, diff, status, stats, summarize, pack, install, monitor, explain, doctor, session, watch, claude_cmd

app = typer.Typer(help="AgentPack — token-aware context packing for AI coding agents.")

for mod in [init, scan, diff, status, stats, summarize, pack, install, monitor, explain, doctor, session, watch, claude_cmd]:
    mod.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
