from __future__ import annotations

import re
from pathlib import Path

from agentpack.integrations.git_hooks import install_git_hooks

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack Context

At the start of every coding task:

1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `agentpack pack --task auto` to refresh context.
3. Read `.agentpack/context.md` — it lists the files most relevant to your task.
4. Use those files as starting points, but verify with actual code before editing.
<!-- agentpack:end -->"""

_BLOCK_RE = re.compile(
    r"<!-- agentpack:start -->.*?<!-- agentpack:end -->",
    re.DOTALL,
)


class CodexInstaller:
    """Configures Codex/OpenAI-specific repo files and auto-repack hooks."""

    def patch_agents_md(self, root: Path) -> str:
        """Insert/update AgentPack block in AGENTS.md. Returns action taken."""
        agents_md = root / "AGENTS.md"

        if not agents_md.exists():
            agents_md.write_text(f"{_AGENTPACK_BLOCK}\n")
            return "created"

        content = agents_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_AGENTPACK_BLOCK, content)
            if new_content != content:
                agents_md.write_text(new_content)
                return "updated"
            return "unchanged"

        agents_md.write_text(content.rstrip() + "\n\n" + _AGENTPACK_BLOCK + "\n")
        return "appended"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="auto")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        return results
