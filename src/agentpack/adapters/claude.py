from __future__ import annotations

import re
from pathlib import Path

from agentpack.adapters.base import BaseAdapter
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_claude

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack Context

Before working on larger tasks, read the generated context pack:

- `.agentpack/context.claude.md`

Regenerate it with:

```bash
agentpack pack --agent claude --task "<task>"
```

Use the context pack as the primary task-specific repo context.

<!-- agentpack:end -->"""

_BLOCK_RE = re.compile(
    r"<!-- agentpack:start -->.*?<!-- agentpack:end -->",
    re.DOTALL,
)


class ClaudeAdapter(BaseAdapter):
    def __init__(self, output: str = ".agentpack/context.claude.md"):
        self._output = output

    def output_path(self, root: Path) -> Path:
        return root / self._output

    def render(self, pack: ContextPack) -> str:
        return render_claude(pack)

    def patch_claude_md(self, root: Path) -> str:
        """Insert/update AgentPack block in CLAUDE.md. Returns action taken."""
        claude_md = root / "CLAUDE.md"

        if not claude_md.exists():
            claude_md.write_text(f"{_AGENTPACK_BLOCK}\n")
            return "created"

        content = claude_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_AGENTPACK_BLOCK, content)
            if new_content != content:
                claude_md.write_text(new_content)
                return "updated"
            return "unchanged"

        claude_md.write_text(content.rstrip() + "\n\n" + _AGENTPACK_BLOCK + "\n")
        return "appended"
