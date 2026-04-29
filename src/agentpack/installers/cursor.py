from __future__ import annotations

import re
from pathlib import Path

from agentpack.integrations.git_hooks import install_git_hooks
from agentpack.integrations.vscode_tasks import install_vscode_tasks

_CURSOR_RULE = """\
<!-- agentpack:rule:start -->
Always read `.agentpack/context.md` at the start of every conversation for
task-specific repo context. If it looks stale, run:
  agentpack pack --agent cursor --task "<task>"
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
description: AgentPack context injection
alwaysApply: true
---

Always read `.agentpack/context.md` at the start of every conversation for
task-specific repo context. If it looks stale or the changed files list is
empty when you expect changes, run:

```bash
agentpack pack --agent cursor --task "<task>"
```
"""
        already = mdc_path.exists()
        if already and mdc_path.read_text() == content:
            return "unchanged"

        mdc_path.write_text(content)
        return "updated" if already else "created"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="cursor")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="cursor")
        return results
