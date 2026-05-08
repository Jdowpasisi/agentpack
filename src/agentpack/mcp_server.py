"""AgentPack MCP server — exposes context packing as MCP tools.

Start with:
    agentpack mcp

Or register in Claude Code settings:
    {
      "mcpServers": {
        "agentpack": {
          "command": "agentpack",
          "args": ["mcp"]
        }
      }
    }

Tools exposed:
    pack_context   — generate/refresh a context pack for a task
    get_context    — read the latest context pack (no repack)
    refresh        — refresh using the current task.md
"""
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    """Walk up from cwd until .agentpack/ found; fall back to cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".agentpack").exists():
            return parent
    return cwd


def serve() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "mcp package required for MCP server. "
            "Install: pip install 'agentpack-cli[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP("agentpack")

    @mcp.tool()
    def pack_context(task: str, mode: str = "balanced", budget: int = 0) -> str:
        """Generate a ranked context pack for the given task.

        Args:
            task: Describe what you're working on (e.g. "fix auth token refresh").
            mode: minimal | balanced (default) | deep
            budget: Token budget, 0 = config default (usually 25000).

        Returns the packed context as a markdown string.
        """
        from agentpack.application.pack_service import PackService, PackRequest
        from agentpack.adapters.detect import detect_agent
        from agentpack.renderers.markdown import render_claude

        root = _repo_root()
        agent = detect_agent(root)
        result = PackService().run(PackRequest(
            root=root,
            agent=agent,
            task=task,
            mode=mode,
            budget=budget,
            since=None,
            refresh=False,
            summary_provider="offline",
        ))
        return render_claude(result.pack)

    @mcp.tool()
    def get_context() -> str:
        """Return the latest pre-built context pack without repacking.

        Fast — just reads the cached file. Use pack_context() to regenerate.
        Returns empty string if no pack exists yet.
        """
        root = _repo_root()
        for candidate in (
            root / ".agentpack" / "context.claude.md",
            root / ".agentpack" / "context.md",
        ):
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        return ""

    @mcp.tool()
    def refresh() -> str:
        """Refresh context using the current task.md (or git-inferred task).

        Equivalent to running `agentpack session refresh`.
        Returns summary of what was packed.
        """
        from agentpack.commands.session import _run_refresh
        from agentpack.session.state import load_session
        from agentpack.adapters.detect import detect_agent

        root = _repo_root()
        state = load_session(root)
        agent = state.agent if state else detect_agent(root)
        mode = state.mode if state else "balanced"

        result = _run_refresh(root, agent, mode, 0)
        if result is None:
            return "Refresh failed."
        return (
            f"Refreshed: {result['files']} files, "
            f"{result['tokens']:,} tokens, "
            f"{result['saving']:.1f}% saving"
        )

    mcp.run()
