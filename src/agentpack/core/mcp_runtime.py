from __future__ import annotations

import importlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

McpRuntimeStatus = Literal["ready", "missing_extra", "command_missing", "server_error", "stdio_waiting"]


@dataclass(frozen=True)
class McpRuntimeCheck:
    status: McpRuntimeStatus
    ok: bool
    detail: str
    remediation: tuple[str, ...] = ()


def check_mcp_runtime(
    *,
    root: Path | None = None,
    command: str = "agentpack",
    timeout_s: float = 1.0,
) -> McpRuntimeCheck:
    """Probe whether the local AgentPack MCP server can be launched by an agent host."""
    binary = shutil.which(command)
    if not binary:
        return McpRuntimeCheck(
            status="command_missing",
            ok=False,
            detail=f"{command} command not found on PATH",
            remediation=("pipx install agentpack-cli",),
        )

    try:
        importlib.import_module("mcp.server.fastmcp")
    except ModuleNotFoundError as exc:
        if str(exc.name or "").startswith("mcp"):
            return McpRuntimeCheck(
                status="missing_extra",
                ok=False,
                detail="Python package `mcp.server.fastmcp` is not importable",
                remediation=_missing_extra_remediation(root),
            )
        return McpRuntimeCheck(
            status="server_error",
            ok=False,
            detail=f"MCP import failed: {exc}",
        )
    except Exception as exc:
        return McpRuntimeCheck(
            status="server_error",
            ok=False,
            detail=f"MCP import failed: {exc}",
        )

    try:
        proc = subprocess.Popen(
            [binary, "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return McpRuntimeCheck(status="server_error", ok=False, detail=str(exc))

    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return McpRuntimeCheck(
            status="stdio_waiting",
            ok=True,
            detail="agentpack mcp started and waited for MCP stdio",
        )

    stdout, stderr = proc.communicate()
    output = (stderr or stdout or "").strip()
    if returncode == 0:
        return McpRuntimeCheck(status="ready", ok=True, detail=output or "agentpack mcp exited successfully")
    return McpRuntimeCheck(
        status="server_error",
        ok=False,
        detail=output or f"agentpack mcp exited with code {returncode}",
    )


def _missing_extra_remediation(root: Path | None) -> tuple[str, ...]:
    commands = ['pipx inject agentpack-cli "agentpack-cli[mcp]"']
    if root is not None and (root / "pyproject.toml").exists() and (root / "src" / "agentpack").exists():
        commands.append('python -m pip install -e ".[mcp]"')
    return tuple(commands)
