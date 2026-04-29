from __future__ import annotations

from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_generic
from agentpack.installers.cursor import CursorInstaller  # noqa: F401


class CursorAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_generic(pack)

    # Delegating install methods — kept for backward compat
    def patch_cursor_rules(self, root: Path) -> str:
        return CursorInstaller().patch_cursor_rules(root)

    def patch_cursor_mdc(self, root: Path) -> str:
        return CursorInstaller().patch_cursor_mdc(root)

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        return CursorInstaller().install_auto_repack(root)
