from __future__ import annotations

from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_antigravity
from agentpack.installers.antigravity import AntigravityInstaller  # noqa: F401


class AntigravityAdapter(BaseAdapter):
    """Writes context as an Antigravity skill at .agent/skills/agentpack/SKILL.md."""

    def __init__(self, output: str = ".agent/skills/agentpack/SKILL.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_antigravity(pack)

    def patch_gemini_md(self, root: Path) -> str:
        return AntigravityInstaller().patch_gemini_md(root)

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        return AntigravityInstaller().install_auto_repack(root)
