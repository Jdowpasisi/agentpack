from __future__ import annotations

from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_generic


class GenericAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_generic(pack)
