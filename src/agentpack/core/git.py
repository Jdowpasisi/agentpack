from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def is_git_repo(root: Path) -> bool:
    out = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    return out is not None and out.strip() == "true"


def changed_files(root: Path) -> set[str]:
    """Unstaged + staged modified/added files."""
    result: set[str] = set()
    for args in [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ]:
        out = _run(args, root)
        if out:
            for line in out.splitlines():
                line = line.strip()
                if line:
                    result.add(line)
    return result


def untracked_files(root: Path) -> set[str]:
    out = _run(["git", "status", "--short"], root)
    result: set[str] = set()
    if not out:
        return result
    for line in out.splitlines():
        if line.startswith("??"):
            result.add(line[3:].strip())
    return result


def recently_modified_files(root: Path, n: int = 20) -> list[str]:
    out = _run(
        ["git", "log", f"--diff-filter=M", "--name-only", "--format=", f"-{n}"],
        root,
    )
    if not out:
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]
