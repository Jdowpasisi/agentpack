from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import typer

from agentpack.commands._shared import _root
from agentpack.core import git as _git
from agentpack.core.config import load_config

_TASK_FILE = ".agentpack/task.md"
_TASK_FILE_DEFAULT_MARKER = "Write or update the current coding task here."
_CODING_PROMPT_RE = re.compile(
    r"(?:fix|add|refactor|impl|implement|update|write|debug|test|build|migrate|remove|delete|rename|optimize)\b",
    re.IGNORECASE,
)
_TASK_STOPWORDS = {
    "add",
    "all",
    "and",
    "bug",
    "build",
    "can",
    "change",
    "changes",
    "code",
    "delete",
    "fix",
    "for",
    "implement",
    "improve",
    "make",
    "please",
    "refactor",
    "remove",
    "task",
    "test",
    "that",
    "the",
    "these",
    "this",
    "update",
    "with",
    "work",
    "write",
    "you",
}


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


def _looks_like_coding_prompt(prompt: str) -> bool:
    """Return True if prompt looks like a coding task (not a slash command or chat)."""
    stripped = prompt.strip()
    if stripped.startswith("/"):
        return False
    return bool(_CODING_PROMPT_RE.search(stripped))


def _prompt_task(prompt: str) -> str:
    if not prompt or not _looks_like_coding_prompt(prompt):
        return ""
    task = " ".join(prompt.strip().split())[:200]
    if not _task_terms(task):
        return ""
    return task


def _task_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", text.lower()):
        for part in re.split(r"[-_]", raw):
            if len(part) >= 3 and part not in _TASK_STOPWORDS:
                terms.add(part)
    return terms


def _looks_like_task_switch(current_task: str, prompt: str, min_terms: int = 1) -> bool:
    """Heuristic: a coding prompt with disjoint concrete terms likely starts a new task."""
    prompt_task = _prompt_task(prompt)
    if not current_task or not prompt_task:
        return False
    if current_task.strip().lower() == prompt_task.lower():
        return False
    current_terms = _task_terms(current_task)
    prompt_terms = _task_terms(prompt_task)
    required_terms = max(1, min_terms)
    if len(current_terms) < required_terms or len(prompt_terms) < required_terms:
        return False
    return bool(current_terms and prompt_terms and current_terms.isdisjoint(prompt_terms))


def _write_task_md(root: Path, task: str) -> None:
    task_path = root / _TASK_FILE
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(task.strip() + "\n", encoding="utf-8")


def _resolve_task(
    root: Path,
    prompt: str,
    *,
    task_switch_detection: bool = True,
    task_switch_min_terms: int = 1,
) -> str:
    """Merge task.md + prompt into best task description for repack."""
    task_md = _load_task_md(root)
    prompt_task = _prompt_task(prompt)
    if (
        task_switch_detection
        and task_md
        and prompt_task
        and _looks_like_task_switch(task_md, prompt_task, min_terms=task_switch_min_terms)
    ):
        return prompt_task
    if task_md:
        return task_md
    if prompt_task:
        return prompt_task
    return "auto"


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


def _load_delta_summary(root: Path) -> str:
    meta_path = root / ".agentpack" / "pack_metadata.json"
    if not meta_path.exists():
        return ""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    freshness = meta.get("freshness") or {}
    delta = freshness.get("delta_summary", "")
    return str(delta).splitlines()[0][:240] if delta else ""


def _infer_live_task(root: Path) -> str:
    """Live task: git priority chain (no stale metadata). Falls back to 'unknown'."""
    try:
        task, _ = _git.infer_task_with_source(root)
        return task
    except Exception:
        return "unknown"


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

    cfg = load_config(root)
    task_md = _load_task_md(root)
    task_switched = bool(
        cfg.hooks.task_switch_detection
        and _looks_like_task_switch(
            task_md,
            prompt,
            min_terms=cfg.hooks.task_switch_min_terms,
        )
    )
    task = _resolve_task(
        root,
        prompt,
        task_switch_detection=cfg.hooks.task_switch_detection,
        task_switch_min_terms=cfg.hooks.task_switch_min_terms,
    )
    if task_switched and task != "auto":
        try:
            _write_task_md(root, task)
        except Exception:
            pass

    current_hash = _current_root_hash(root)
    reminded_hash = snap_sentinel.read_text().strip() if snap_sentinel.exists() else None
    repo_changed = current_hash != reminded_hash
    packed_task = _load_pack_task(root)
    pack_task_changed = bool(task != "auto" and packed_task and packed_task != task)

    should_repack = repo_changed or task_switched or pack_task_changed

    if should_repack:
        if task != "auto":
            try:
                _write_task_md(root, task)
            except Exception:
                pass
        subprocess.Popen(
            ["agentpack", "pack", "--task", "auto", "--mode", "balanced", "--since", "HEAD~1"],
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
            status_note = "(repacking — call pack_context for fresh results)" if should_repack else "(index fresh)"
            current_task = _load_task_md(root) or _infer_live_task(root)
            delta = _load_delta_summary(root)
            msg = (
                f"AgentPack {status_note}\n"
                f"task: {current_task}\n"
                + (f"delta: {delta}\n" if delta else "")
                +
                f"top files:\n{files_lines}\n"
                f"Call agentpack_get_delta_context() for delta or agentpack_pack_context(task=\"...\") for full ranked context."
            )
        else:
            msg = (
                "AgentPack active. No pack yet — call agentpack_pack_context(task=\"...\") "
                "to build context for this task."
            )
    else:
        hints = _load_hints(root, n=8)
        current_task = _load_task_md(root) or _infer_live_task(root)
        if hints:
            delta = _load_delta_summary(root)
            files_lines = "\n".join(
                f"  - {h['path']}" + (f" — {h['why']}" if h.get("why") else "")
                for h in hints
            )
            changed_note = " (repacking in background)" if should_repack else ""
            msg = (
                f"AgentPack context{changed_note}\n"
                f"task: {current_task}\n"
                + (f"delta: {delta}\n" if delta else "")
                +
                f"top files:\n{files_lines}\n\n"
                f"For richer context, install MCP: agentpack install --agent claude"
            )
        else:
            msg = (
                "AgentPack active. Write `.agentpack/task.md`, then run `agentpack pack --task auto` to build context.\n"
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
