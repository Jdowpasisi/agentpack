from __future__ import annotations

from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_claude

# Re-export installer symbols for backward compatibility
from agentpack.installers.claude import (  # noqa: F401
    ClaudeInstaller,
    _AGENTPACK_BLOCK,
    _BLOCK_RE,
)


class ClaudeAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.claude.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_claude(pack)

    # Delegating install methods — kept for backward compat with any callers using adapter directly
    def patch_claude_md(self, root: Path) -> str:
        return ClaudeInstaller().patch_claude_md(root)

    def patch_claude_settings(self, root: Path, global_install: bool = False) -> str:
        return ClaudeInstaller().patch_claude_settings(root, global_install)
