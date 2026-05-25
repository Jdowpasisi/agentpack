from __future__ import annotations

import typer



def register(app: typer.Typer) -> None:
    @app.command("mcp")
    def mcp_server() -> None:
        """Start the AgentPack MCP server (tools: route_task, pack_context, get_context, refresh)."""
        from agentpack.mcp_server import serve
        serve()
