from __future__ import annotations

import typer

from agentpack.commands._shared import console


def register(app: typer.Typer) -> None:
    @app.command("mcp")
    def mcp_server() -> None:
        """Start the AgentPack MCP server (tools: pack_context, get_context, refresh)."""
        from agentpack.mcp_server import serve
        serve()
