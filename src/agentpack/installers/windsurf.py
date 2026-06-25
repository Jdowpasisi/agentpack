from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.command_surface import fallback_agent_guidance, prompt_quality_guidance, refresh_commands
from agentpack.integrations.git_hooks import install_git_hooks
from agentpack.integrations.vscode_tasks import install_vscode_tasks

def _windsurf_rule() -> str:
    commands = refresh_commands("windsurf")
    stale_refresh = "rerun the guard command" if commands.used_guard else "rerun the refresh command"
    thread_line = (
        "\nFor multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. "
        f"Use `{commands.thread_auto}` or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings."
        if commands.thread_auto
        else ""
    )
    return f"""\
<!-- agentpack:rule:start -->
At the start of every coding task:
1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `{commands.primary}`.
3. Prefer AgentPack MCP if available. Call `agentpack_readiness()` to prove live tool exposure, then `agentpack_get_context()` for current context or `agentpack_pack_context(task="<task>")` for a new task. MCP is the active path because it auto-refreshes stale task/repo context.
4. If MCP is unavailable, read `.agentpack/context.md`. Treat it as fallback; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, {stale_refresh} before using selected files.
5. Use files listed in context as starting points, but verify with actual code before editing.
6. Use JSON programmatically for configs, storage, hooks, and tool protocols. Use TOON for agent-facing structured context or prompt payloads unless an external contract requires JSON.
When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the refresh command before editing.
If context is missing: {commands.context_missing}.
{fallback_agent_guidance()}
{prompt_quality_guidance()}{thread_line}
<!-- agentpack:rule:end -->"""

_RULE_RE = re.compile(
    r"<!-- agentpack:rule:start -->.*?<!-- agentpack:rule:end -->",
    re.DOTALL,
)


class WindsurfInstaller:
    """Configures Windsurf-specific repo files and auto-repack hooks."""

    def patch_windsurfrules(self, root: Path) -> str:
        """Insert/update agentpack rule in .windsurfrules. Returns action taken."""
        rules_file = root / ".windsurfrules"

        if not rules_file.exists():
            rules_file.write_text(f"{_windsurf_rule()}\n")
            return "created"

        content = rules_file.read_text()
        if _RULE_RE.search(content):
            new_content = _RULE_RE.sub(_windsurf_rule(), content)
            if new_content != content:
                rules_file.write_text(new_content)
                return "updated"
            return "unchanged"

        rules_file.write_text(content.rstrip() + "\n\n" + _windsurf_rule() + "\n")
        return "appended"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="auto")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="auto")
        return results
