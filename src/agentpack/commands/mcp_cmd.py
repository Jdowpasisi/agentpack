from __future__ import annotations

import typer



def register(app: typer.Typer) -> None:
    @app.command("mcp")
    def mcp_server() -> None:
        """Start the stdio MCP server for agent hosts; use manually only as a bounded diagnostic."""
        from agentpack.mcp_server import serve
        serve()
