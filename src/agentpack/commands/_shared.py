from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()

_ROOT = Path(".")


def _root() -> Path:
    return _ROOT
