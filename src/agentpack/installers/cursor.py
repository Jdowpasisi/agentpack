from __future__ import annotations

import re
from pathlib import Path

from agentpack.integrations.git_hooks import install_git_hooks
from agentpack.integrations.vscode_tasks import install_vscode_tasks

_CURSOR_RULE = """\
<!-- agentpack:rule:start -->
At the start of every coding task:
1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `agentpack guard --agent cursor --repair-stale --refresh-context`. This is the executable pre-edit gate for non-MCP paths.
3. Prefer AgentPack MCP if available. MCP is the active path. Call `agentpack_route_task(task="<task>")` first to get files, rules, skills, commands, and safety warnings.
4. Call `agentpack_pack_context(task="<task>")` only when full packed context is needed, or `agentpack_get_context()` for current context.
5. If MCP is unavailable, read `.agentpack/context.md`. Treat it as fallback; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, rerun the guard command before using selected files.
6. Use files listed in context as starting points, but verify with actual code before editing.
When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the guard command before editing.
If context is missing: write `.agentpack/task.md`, then run `agentpack guard --agent cursor --repair-stale --refresh-context`.
For multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. Use `AGENTPACK_THREAD_ID=<stable-id> agentpack guard --agent cursor --repair-stale --refresh-context --thread auto` or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings.
<!-- agentpack:rule:end -->"""

_RULE_RE = re.compile(
    r"<!-- agentpack:rule:start -->.*?<!-- agentpack:rule:end -->",
    re.DOTALL,
)


class CursorInstaller:
    """Configures Cursor-specific repo files and auto-repack hooks."""

    def patch_cursor_rules(self, root: Path) -> str:
        """Insert/update agentpack rule in .cursorrules. Returns action taken."""
        rules_file = root / ".cursorrules"

        if not rules_file.exists():
            rules_file.write_text(f"{_CURSOR_RULE}\n")
            return "created"

        content = rules_file.read_text()
        if _RULE_RE.search(content):
            new_content = _RULE_RE.sub(_CURSOR_RULE, content)
            if new_content != content:
                rules_file.write_text(new_content)
                return "updated"
            return "unchanged"

        rules_file.write_text(content.rstrip() + "\n\n" + _CURSOR_RULE + "\n")
        return "appended"

    def patch_cursor_mdc(self, root: Path) -> str:
        """Write agentpack rule as a Cursor .mdc rule file (Cursor v0.43+)."""
        rules_dir = root / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        mdc_path = rules_dir / "agentpack.mdc"

        content = """\
---
description: AgentPack session context injection
alwaysApply: true
---

At the start of every coding task:

1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `agentpack guard --agent cursor --repair-stale --refresh-context`. This is the executable pre-edit gate for non-MCP paths.
3. Prefer AgentPack MCP if available. MCP is the active path. Call `agentpack_route_task(task="<task>")` first to get files, rules, skills, commands, and safety warnings.
4. Call `agentpack_pack_context(task="<task>")` only when full packed context is needed, or `agentpack_get_context()` for current context.
5. If MCP is unavailable, read `.agentpack/context.md`. Treat it as fallback; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, rerun the guard command before using selected files.
6. Use files listed in context as starting points, but verify with actual code before editing.

When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the guard command before editing.

If context is missing: write `.agentpack/task.md`, then run `agentpack guard --agent cursor --repair-stale --refresh-context`.

For multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. Use `AGENTPACK_THREAD_ID=<stable-id> agentpack guard --agent cursor --repair-stale --refresh-context --thread auto` or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings.
"""
        already = mdc_path.exists()
        if already and mdc_path.read_text() == content:
            return "unchanged"

        mdc_path.write_text(content)
        return "updated" if already else "created"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="auto")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="auto")
        return results
