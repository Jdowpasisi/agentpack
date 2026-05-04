from __future__ import annotations

import re
from pathlib import Path

from agentpack.integrations.git_hooks import install_git_hooks

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack Context

If `.agentpack/session.json` exists and `"active": true`:

1. Read `.agentpack/context.md` before making code changes.
2. For a new coding task, write a one-line summary to `.agentpack/task.md`.
3. Re-read `.agentpack/context.md` after watch mode refreshes it.
4. Use AgentPack-selected files as starting points, not as absolute truth.
5. If context is missing or stale: `agentpack session refresh`
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
        hook_results = install_git_hooks(root, agent="codex")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        return results
