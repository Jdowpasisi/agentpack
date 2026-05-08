from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from agentpack.session.state import CONTEXT_FILE, COMPACT_FILE, TASK_FILE

console = Console()

_ROOT = Path(".")


def _root() -> Path:
    return _ROOT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _atomic_write(path: Path, text: str) -> None:
    """Write to a temp file in the same dir, then rename — atomic on POSIX."""
    dir_ = path.parent
    try:
        fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        path.write_text(text, encoding="utf-8")


def run_refresh(
    root: Path,
    agent: str,
    mode: str,
    budget: int,
) -> Optional[dict]:
    """Run PackService and write context + compact files. Returns stats dict or None on error."""
    try:
        from agentpack.application.pack_service import PackService, PackRequest
        from agentpack.core import git
        from agentpack.renderers.compact import render_compact
        from agentpack.renderers.markdown import render_generic, render_claude

        task_path = root / TASK_FILE
        if task_path.exists():
            raw = task_path.read_text(encoding="utf-8").strip()
            lines = [line for line in raw.splitlines() if line.strip() and not line.startswith("#")]
            task = lines[0].strip() if lines else ""
        else:
            task = ""

        if not task:
            if git.is_git_repo(root):
                task = git.infer_task_from_git(root)
            else:
                task = "Current branch changes and likely related files"

        result = PackService().run(PackRequest(
            root=root,
            agent=agent,
            task=task,
            mode=mode,
            budget=budget,
            since=None,
            refresh=False,
        ))

        context_path = root / CONTEXT_FILE
        context_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(context_path, render_generic(result.pack))
        _atomic_write(root / ".agentpack/context.claude.md", render_claude(result.pack))

        compact_path = root / COMPACT_FILE
        _atomic_write(compact_path, render_compact(result.pack))

        return {
            "files": len(result.pack.selected_files),
            "tokens": result.packed_tokens,
            "saving": result.saving_pct,
            "out_path": result.out_path,
        }
    except Exception as e:
        console.print(f"[red]Error during refresh: {e}[/]")
        return None
