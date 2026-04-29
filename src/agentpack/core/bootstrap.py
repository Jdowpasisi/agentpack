from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_initialized(root: Path) -> bool:
    return (root / ".agentpack" / "config.toml").exists()


def bootstrap_if_needed(root: Path, agent: str = "claude", silent: bool = True) -> bool:
    """Run init + pack if not already configured. Returns True if bootstrapped.

    Safe to call from git hooks or shell hooks — catches all exceptions so it
    never breaks the calling tool.
    """
    if is_initialized(root):
        return False

    # Don't bootstrap non-git directories or directories that look like home/system dirs
    if not (root / ".git").exists():
        return False

    # Skip very large directories (>5000 files) — likely not a real project root
    try:
        file_count = sum(1 for _ in root.rglob("*") if _.is_file())
        if file_count > 5000:
            return False
    except OSError:
        return False

    try:
        kwargs: dict = {"capture_output": silent, "text": True}
        subprocess.run(
            [sys.executable, "-m", "agentpack", "init", "--yes"],
            cwd=str(root), **kwargs
        )
        subprocess.run(
            [sys.executable, "-m", "agentpack", "pack",
             "--agent", agent, "--task", "auto", "--mode", "balanced"],
            cwd=str(root), **kwargs
        )
        return True
    except Exception:
        return False
