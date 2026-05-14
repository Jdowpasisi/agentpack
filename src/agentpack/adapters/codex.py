from __future__ import annotations

from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_generic
from agentpack.installers.codex import CodexInstaller  # noqa: F401


class CodexAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_generic(pack)

    # Delegating install methods — kept for backward compat
    def patch_agents_md(self, root: Path) -> str:
        return CodexInstaller().patch_agents_md(root)

    def patch_codex_hooks(self, root: Path) -> str:
        return CodexInstaller().patch_codex_hooks(root)

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        return CodexInstaller().install_auto_repack(root)
