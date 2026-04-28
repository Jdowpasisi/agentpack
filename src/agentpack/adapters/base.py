from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agentpack.core.models import ContextPack


class BaseAdapter(ABC):
    @abstractmethod
    def output_path(self, root: Path) -> Path:
        ...

    @abstractmethod
    def render(self, pack: ContextPack) -> str:
        ...

    def write(self, pack: ContextPack, root: Path) -> Path:
        out = self.output_path(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.render(pack))
        return out
