from __future__ import annotations

import re
from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.core.git_hooks import install_git_hooks
from agentpack.core.vscode_tasks import install_vscode_tasks
from agentpack.renderers.markdown import render_generic

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack Context

Before working on any task, read the generated context pack:

- `.agentpack/context.md`

Regenerate it with:

```bash
agentpack pack --agent windsurf --task "<task>"
```

Use the context pack as the primary task-specific repo context.
<!-- agentpack:end -->"""

_BLOCK_RE = re.compile(
    r"<!-- agentpack:start -->.*?<!-- agentpack:end -->",
    re.DOTALL,
)

_WINDSURF_RULE = """\
<!-- agentpack:rule:start -->
Always read `.agentpack/context.md` at the start of every conversation for
task-specific repo context. If it looks stale, run:
  agentpack pack --agent windsurf --task "<task>"
<!-- agentpack:rule:end -->"""

_RULE_RE = re.compile(
    r"<!-- agentpack:rule:start -->.*?<!-- agentpack:rule:end -->",
    re.DOTALL,
)


class WindsurfAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_generic(pack)

    def patch_windsurfrules(self, root: Path) -> str:
        """Insert/update agentpack rule in .windsurfrules. Returns action taken."""
        rules_file = root / ".windsurfrules"

        if not rules_file.exists():
            rules_file.write_text(f"{_WINDSURF_RULE}\n")
            return "created"

        content = rules_file.read_text()
        if _RULE_RE.search(content):
            new_content = _RULE_RE.sub(_WINDSURF_RULE, content)
            if new_content != content:
                rules_file.write_text(new_content)
                return "updated"
            return "unchanged"

        rules_file.write_text(content.rstrip() + "\n\n" + _WINDSURF_RULE + "\n")
        return "appended"

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks + VS Code tasks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        hook_results = install_git_hooks(root, agent="windsurf")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        results["vscode:tasks"] = install_vscode_tasks(root, agent="windsurf")
        return results
