from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.command_surface import (
    fallback_agent_guidance,
    mcp_diagnostic_guidance,
    prompt_quality_guidance,
    refresh_commands,
)
from agentpack.integrations.git_hooks import install_git_hooks
from agentpack.integrations.vscode_tasks import install_vscode_tasks

def _gemini_block() -> str:
    commands = refresh_commands("antigravity")
    stale_refresh = "rerun the guard command" if commands.used_guard else "rerun the refresh command"
    thread_line = (
        "\nFor multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. "
        f"Use `{commands.thread_auto}` or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings."
        if commands.thread_auto
        else ""
    )
    return f"""\
<!-- agentpack:block:start -->
skills:
  - agentpack

At the start of every coding task:
1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `{commands.primary}`.
3. Prefer AgentPack MCP if available. MCP is the active path. Call `agentpack_readiness()` to prove live tool exposure, then `agentpack_route_task(task="<task>")` to get files, rules, skills, commands, and safety warnings.
4. Call `agentpack_pack_context(task="<task>")` only when full packed context is needed, or `agentpack_get_context()` for current context.
5. If MCP is unavailable, read `.agent/skills/agentpack/SKILL.md`. Treat it as fallback; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, {stale_refresh} before using selected files.
6. Use files listed in context as starting points, but verify with actual code before editing.
7. Use JSON programmatically for configs, storage, hooks, and tool protocols. Use TOON for agent-facing structured context or prompt payloads unless an external contract requires JSON.

When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the refresh command before editing.

{fallback_agent_guidance()}

{mcp_diagnostic_guidance("antigravity")}

{prompt_quality_guidance()}{thread_line}
<!-- agentpack:block:end -->"""

_BLOCK_RE = re.compile(
    r"<!-- agentpack:block:start -->.*?<!-- agentpack:block:end -->",
    re.DOTALL,
)


class AntigravityInstaller:
    """Configures Antigravity-specific repo files and auto-repack hooks."""

    def patch_gemini_md(self, root: Path) -> str:
        """Insert/update agentpack skill reference in GEMINI.md. Returns action taken."""
        gemini_md = root / "GEMINI.md"

        if not gemini_md.exists():
            gemini_md.write_text(f"{_gemini_block()}\n")
            return "created"

        content = gemini_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_gemini_block(), content)
            if new_content != content:
                gemini_md.write_text(new_content)
                return "updated"
            return "unchanged"

        gemini_md.write_text(content.rstrip() + "\n\n" + _gemini_block() + "\n")
        return "appended"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="auto")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="auto")
        return results
