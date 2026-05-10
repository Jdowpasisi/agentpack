from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from agentpack.commands._shared import _root


def register(app: typer.Typer) -> None:
    @app.command(name="hook")
    def hook(
        event: str = typer.Option("UserPromptSubmit", "--event", help="Hook event name."),
    ) -> None:
        """Run as a Claude Code hook. Reads stdin (JSON), emits additionalContext."""
        if event == "UserPromptSubmit":
            _run_user_prompt_submit(_root())
        else:
            sys.exit(0)


def _mcp_installed(root: Path) -> bool:
    """Check if agentpack MCP server is configured for this project or globally."""
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


def _load_top_files(root: Path, n: int = 5) -> list[dict]:
    """Return top-n selected files from last metrics record."""
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
            paths = rec.get("selected_paths", [])
            if paths:
                return [{"path": p} for p in paths[:n]]
    except Exception:
        pass
    return []


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


def _run_user_prompt_submit(root: Path) -> None:
    import subprocess

    snap_sentinel = root / ".agentpack" / ".mcp_reminded"

    # Read prompt from stdin
    try:
        hook_data = json.loads(sys.stdin.read())
        prompt = hook_data.get("prompt", "")
    except Exception:
        prompt = ""

    task = prompt[:200].strip() if prompt else "auto"

    current_hash = _current_root_hash(root)
    reminded_hash = snap_sentinel.read_text().strip() if snap_sentinel.exists() else None

    repo_changed = current_hash != reminded_hash

    if repo_changed:
        subprocess.Popen(
            ["agentpack", "pack", "--task", task or "auto", "--mode", "balanced"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            snap_sentinel.write_text(current_hash or "1")
        except Exception:
            pass

    has_mcp = _mcp_installed(root)

    if has_mcp:
        # Option B: tiny hint — task + top files list, no content
        last_task = _load_pack_task(root)
        top_files = _load_top_files(root, n=5)

        if top_files:
            files_lines = "\n".join(f"  - {f['path']}" for f in top_files)
            if repo_changed:
                status_note = "(repacking — call pack_context for fresh results)"
            else:
                status_note = "(index fresh)"
            msg = (
                f"AgentPack {status_note}\n"
                f"last task: {last_task or 'unknown'}\n"
                f"top files:\n{files_lines}\n"
                f"Call agentpack_pack_context(task=\"...\") for full ranked context."
            )
        else:
            # No pack yet
            msg = (
                "AgentPack active. No pack yet — call agentpack_pack_context(task=\"...\") "
                "to build context for this task."
            )
    else:
        # Capped fallback: top files + compact reasons, no full content, hard cap 3k chars
        top_files = _load_top_files(root, n=8)
        last_task = _load_pack_task(root)

        if top_files:
            files_lines = "\n".join(f"  - {f['path']}" for f in top_files)
            changed_note = " (repacking in background)" if repo_changed else ""
            msg = (
                f"AgentPack context{changed_note}\n"
                f"task: {last_task or 'unknown'}\n"
                f"top files:\n{files_lines}\n\n"
                f"For richer context, install MCP: agentpack install --agent claude"
            )
        else:
            msg = (
                "AgentPack active. Run `agentpack pack --task \"<task>\"` to build context.\n"
                "For auto context, install MCP: agentpack install --agent claude"
            )

        # Hard cap: 3000 chars
        if len(msg) > 3000:
            msg = msg[:2970] + "\n... [truncated]"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }
    print(json.dumps(output))
