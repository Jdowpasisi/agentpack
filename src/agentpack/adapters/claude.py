from __future__ import annotations

import json
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

    def patch_claude_settings(self, root: Path, global_install: bool = False) -> str:
        """Merge agentpack hooks into .claude/settings.json. Returns action taken."""
        if global_install:
            settings_path = Path.home() / ".claude" / "settings.json"
        else:
            settings_path = root / ".claude" / "settings.json"

        settings_path.parent.mkdir(parents=True, exist_ok=True)

        existing: dict = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text())
            except json.JSONDecodeError:
                existing = {}

        hooks = existing.setdefault("hooks", {})

        # SessionStart: clear injection sentinel so first prompt of each session injects context
        session_start = hooks.setdefault("SessionStart", [])
        sentinel_cmd = "rm -f .agentpack/.context_injected"
        already_has_session_hook = any(
            any(h.get("command", "") == sentinel_cmd for h in entry.get("hooks", []))
            for entry in session_start
        )
        if not already_has_session_hook:
            session_start.append({"hooks": [{"type": "command", "command": sentinel_cmd}]})

        # UserPromptSubmit: auto-repack when stale, inject context once per session
        user_prompt = hooks.setdefault("UserPromptSubmit", [])
        inject_command = (
            "python3 -c \"\n"
            "import json, pathlib, subprocess, sys\n"
            "status = subprocess.run(['agentpack', 'status'], capture_output=True, text=True)\n"
            "repacked = status.returncode != 0\n"
            "if repacked:\n"
            "    subprocess.run(['agentpack', 'pack', '--task', 'auto', '--mode', 'balanced'], capture_output=True)\n"
            "sentinel = pathlib.Path('.agentpack/.context_injected')\n"
            "already_injected = sentinel.exists()\n"
            "if repacked or not already_injected:\n"
            "    p = pathlib.Path('.agentpack/context.claude.md')\n"
            "    if not p.exists(): sys.exit(0)\n"
            "    content = p.read_text()\n"
            "    if len(content) > 60000: content = content[:60000] + '\\n... [truncated]'\n"
            "    sentinel.write_text('1')\n"
            "    label = 'repacked and injected' if repacked else 'injected (session start)'\n"
            "    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': f'[agentpack: {label}]\\n\\n' + content}}))\n"
            "\""
        )
        already_has_prompt_hook = any(
            any(h.get("command", "") == inject_command for h in entry.get("hooks", []))
            for entry in user_prompt
        )
        if not already_has_prompt_hook:
            user_prompt.append({
                "hooks": [{
                    "type": "command",
                    "command": inject_command,
                    "timeout": 15,
                    "statusMessage": "Checking agentpack freshness...",
                }]
            })

        action = "unchanged"
        if not already_has_session_hook or not already_has_prompt_hook:
            settings_path.write_text(json.dumps(existing, indent=2) + "\n")
            action = "updated" if settings_path.exists() else "created"

        return action
