from __future__ import annotations

import re
from pathlib import Path

from agentpack.integrations.git_hooks import install_git_hooks
from agentpack.integrations.vscode_tasks import install_vscode_tasks

_GEMINI_BLOCK = """\
<!-- agentpack:block:start -->
skills:
  - agentpack
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
            gemini_md.write_text(f"{_GEMINI_BLOCK}\n")
            return "created"

        content = gemini_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_GEMINI_BLOCK, content)
            if new_content != content:
                gemini_md.write_text(new_content)
                return "updated"
            return "unchanged"

        gemini_md.write_text(content.rstrip() + "\n\n" + _GEMINI_BLOCK + "\n")
        return "appended"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="antigravity")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="antigravity")
        return results
