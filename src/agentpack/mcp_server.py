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

import json
import sys
from pathlib import Path

from agentpack.core.token_estimator import estimate_tokens


def _repo_root() -> Path:
    """Walk up from cwd until .agentpack/ found; fall back to cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".agentpack").exists():
            return parent
    return cwd


def _truncate_to_budget(text: str, max_tokens: int = 20000) -> str:
    """Truncate packed context to fit within max_tokens (estimated via tiktoken, falls back to len//4)."""
    if estimate_tokens(text) <= max_tokens:
        return text

    split_marker = "\n## File Context"
    marker_pos = text.find(split_marker)
    if marker_pos == -1:
        budget_chars = max_tokens * 4
        truncated = text[:budget_chars]
        omit_files = max(1, (len(text) - budget_chars) // 2000)
        return truncated + f"\n\n> [Truncated: {omit_files} files omitted to fit context window. Use get_context() to read full pack or narrow the task.]"

    header = text[:marker_pos]
    file_section = text[marker_pos:]

    if estimate_tokens(header) >= max_tokens:
        return header + "\n\n> [Truncated: file context omitted to fit context window. Use get_context() to read full pack or narrow the task.]"

    blocks = file_section.split("\n### ")
    # blocks[0] is the "## File Context" heading; blocks[1:] are individual files
    accumulated = blocks[0]
    total_files = len(blocks) - 1
    kept_files = 0
    for block in blocks[1:]:
        candidate = accumulated + "\n### " + block
        if estimate_tokens(header + candidate) > max_tokens:
            break
        accumulated = candidate
        kept_files += 1

    omitted = total_files - kept_files
    if omitted > 0:
        return header + accumulated + f"\n\n> [Truncated: {omitted} files omitted to fit context window. Use get_context() to read full pack or narrow the task.]"
    return header + accumulated


def _get_context_impl(root: Path) -> str:
    """Read the latest pre-built context pack from root, with staleness header."""
    pack_path = None
    for candidate in (
        root / ".agentpack" / "context.claude.md",
        root / ".agentpack" / "context.md",
    ):
        if candidate.exists():
            pack_path = candidate
            break
    if pack_path is None:
        return ""

    content = pack_path.read_text(encoding="utf-8")

    metadata_path = root / ".agentpack" / "pack_metadata.json"
    snapshot_path = root / ".agentpack" / "snapshots" / "latest.json"

    metadata = None
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = None

    snapshot = None
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            snapshot = None

    generated_at = metadata.get("generated_at", "unknown") if metadata else "unknown"
    token_estimate = metadata.get("token_estimate", 0) if metadata else 0

    if metadata is None or snapshot is None or metadata.get("snapshot_root_hash") != snapshot.get("root_hash"):
        header = f"> **Stale context** — repo changed since last pack (generated: {generated_at}). Run pack_context() to refresh.\n\n"
    else:
        header = f"> Context is fresh (generated: {generated_at}, {token_estimate:,} tokens).\n\n"

    return header + content


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
    def pack_context(task: str, mode: str = "balanced", budget: int = 0, max_tokens: int = 20000) -> str:
        """Generate a ranked context pack for the given task.

        Args:
            task: Describe what you're working on (e.g. "fix auth token refresh").
            mode: minimal | balanced (default) | deep
            budget: Token budget, 0 = config default (usually 25000).
            max_tokens: Maximum tokens to return (default 20000). Increase for deep context.

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
        ))
        return _truncate_to_budget(render_claude(result.pack), max_tokens)

    @mcp.tool()
    def get_context() -> str:
        """Return the latest pre-built context pack without repacking.

        Fast — just reads the cached file. Use pack_context() to regenerate.
        Returns empty string if no pack exists yet.
        """
        return _get_context_impl(_repo_root())

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
