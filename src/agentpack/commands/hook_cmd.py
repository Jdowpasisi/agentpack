from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from agentpack.commands._shared import _root

_TASK_FILE = ".agentpack/task.md"
_TASK_FILE_DEFAULT_MARKER = "Write or update the current coding task here."


def register(app: typer.Typer) -> None:
    @app.command(name="hook")
    def hook(
        event: str = typer.Option("UserPromptSubmit", "--event", help="Hook event name."),
    ) -> None:
        """Run as a Claude Code hook. Reads stdin (JSON), emits additionalContext."""
        root = _root()
        if event == "UserPromptSubmit":
            _run_user_prompt_submit(root)
        elif event == "SessionStart":
            _run_session_start(root)
        else:
            sys.exit(0)


# ---------------------------------------------------------------------------
# Public helpers (tested directly)
# ---------------------------------------------------------------------------

def _mcp_installed(root: Path) -> bool:
    local_mcp = root / ".mcp.json"
    if local_mcp.exists():
        try:
            cfg = json.loads(local_mcp.read_text())
            if "agentpack" in cfg.get("mcpServers", {}):
                return True
        except Exception:
            pass
    global_settings = Path.home() / ".claude" / "settings.json"
    if global_settings.exists():
        try:
            cfg = json.loads(global_settings.read_text())
            if "agentpack" in cfg.get("mcpServers", {}):
                return True
        except Exception:
            pass
    return False


def _load_task_md(root: Path) -> str:
    """Return task.md content if user has written a real task (not the default placeholder)."""
    task_path = root / _TASK_FILE
    if not task_path.exists():
        return ""
    try:
        content = task_path.read_text(encoding="utf-8").strip()
        # Strip markdown heading
        lines = [ln for ln in content.splitlines() if not ln.startswith("#")]
        body = "\n".join(lines).strip()
        if not body or _TASK_FILE_DEFAULT_MARKER in body:
            return ""
        return body[:200]
    except Exception:
        return ""


def _resolve_task(root: Path, prompt: str) -> str:
    """Merge task.md + prompt into best task description for repack."""
    task_md = _load_task_md(root)
    if task_md:
        return task_md
    return prompt[:200].strip() if prompt else "auto"


def _load_hints(root: Path, n: int = 5) -> list[dict]:
    """Return top-n selected_hints (path + why) from last metrics record."""
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if not metrics_path.exists():
        return []
    try:
        lines = metrics_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            hints = rec.get("selected_hints", [])
            if hints:
                return hints[:n]
            # Fallback: old metrics without hints
            paths = rec.get("selected_paths", [])
            if paths:
                return [{"path": p, "why": ""} for p in paths[:n]]
    except Exception:
        pass
    return []


def _load_top_files(root: Path, n: int = 5) -> list[dict]:
    """Alias kept for backward compat with tests."""
    return _load_hints(root, n)


def _load_pack_task(root: Path) -> str:
    meta_path = root / ".agentpack" / "pack_metadata.json"
    if not meta_path.exists():
        return ""
    try:
        return json.loads(meta_path.read_text()).get("task", "")
    except Exception:
        return ""


def _current_root_hash(root: Path) -> str | None:
    snap = root / ".agentpack" / "snapshots" / "latest.json"
    if not snap.exists():
        return None
    try:
        return json.loads(snap.read_text()).get("root_hash")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _run_session_start(root: Path) -> None:
    """Clear sentinels so first prompt gets fresh context."""
    for sentinel in [
        root / ".agentpack" / ".mcp_reminded",
        root / ".agentpack" / ".context_injected",
    ]:
        try:
            sentinel.unlink(missing_ok=True)
        except Exception:
            pass
    # No output needed — SessionStart hooks don't inject additionalContext


def _run_user_prompt_submit(root: Path) -> None:
    snap_sentinel = root / ".agentpack" / ".mcp_reminded"

    try:
        hook_data = json.loads(sys.stdin.read())
        prompt = hook_data.get("prompt", "")
    except Exception:
        prompt = ""

    task = _resolve_task(root, prompt)

    current_hash = _current_root_hash(root)
    reminded_hash = snap_sentinel.read_text().strip() if snap_sentinel.exists() else None
    repo_changed = current_hash != reminded_hash

    if repo_changed:
        subprocess.Popen(
            ["agentpack", "pack", "--task", task, "--mode", "balanced", "--since", "HEAD~1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            snap_sentinel.write_text(current_hash or "1")
        except Exception:
            pass

    has_mcp = _mcp_installed(root)

    if has_mcp:
        hints = _load_hints(root, n=5)
        if hints:
            files_lines = "\n".join(
                f"  - {h['path']}" + (f" — {h['why']}" if h.get("why") else "")
                for h in hints
            )
            status_note = "(repacking — call pack_context for fresh results)" if repo_changed else "(index fresh)"
            current_task = _load_task_md(root) or _load_pack_task(root) or "unknown"
            msg = (
                f"AgentPack {status_note}\n"
                f"task: {current_task}\n"
                f"top files:\n{files_lines}\n"
                f"Call agentpack_pack_context(task=\"...\") for full ranked context."
            )
        else:
            msg = (
                "AgentPack active. No pack yet — call agentpack_pack_context(task=\"...\") "
                "to build context for this task."
            )
    else:
        hints = _load_hints(root, n=8)
        current_task = _load_task_md(root) or _load_pack_task(root) or "unknown"
        if hints:
            files_lines = "\n".join(
                f"  - {h['path']}" + (f" — {h['why']}" if h.get("why") else "")
                for h in hints
            )
            changed_note = " (repacking in background)" if repo_changed else ""
            msg = (
                f"AgentPack context{changed_note}\n"
                f"task: {current_task}\n"
                f"top files:\n{files_lines}\n\n"
                f"For richer context, install MCP: agentpack install --agent claude"
            )
        else:
            msg = (
                "AgentPack active. Run `agentpack pack --task \"<task>\"` to build context.\n"
                "For auto context, install MCP: agentpack install --agent claude"
            )

        if len(msg) > 3000:
            msg = msg[:2970] + "\n... [truncated]"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }))
