from __future__ import annotations

import json
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

When the user switches to a different coding task, repeat steps 1-3 before editing.
<!-- agentpack:end -->"""

_BLOCK_RE = re.compile(
    r"<!-- agentpack:start -->.*?<!-- agentpack:end -->",
    re.DOTALL,
)

_SESSION_START_HOOK = {
    "type": "command",
    "command": "agentpack hook --event SessionStart",
}

_USER_PROMPT_SUBMIT_HOOK = {
    "type": "command",
    "command": "agentpack hook --event UserPromptSubmit",
    "timeout": 5,
    "statusMessage": "Checking agentpack index...",
}


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

    def patch_codex_hooks(self, root: Path) -> str:
        """Merge AgentPack lifecycle hooks into .codex/hooks.json."""
        hooks_path = root / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        existed = hooks_path.exists()

        existing: dict = {}
        if existed:
            try:
                existing = json.loads(hooks_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}

        hooks = existing.setdefault("hooks", {})
        changed = False
        changed |= self._ensure_hook(hooks, "SessionStart", _SESSION_START_HOOK)
        changed |= self._ensure_hook(hooks, "UserPromptSubmit", _USER_PROMPT_SUBMIT_HOOK)

        new_content = json.dumps(existing, indent=2) + "\n"
        if hooks_path.exists() and hooks_path.read_text(encoding="utf-8") == new_content:
            return "unchanged"
        hooks_path.write_text(new_content, encoding="utf-8")
        return "updated" if existed else "created"

    def _ensure_hook(self, hooks: dict, event: str, hook: dict) -> bool:
        entries = hooks.setdefault(event, [])
        for entry in entries:
            for existing_hook in entry.get("hooks", []):
                if existing_hook.get("type") == hook["type"] and existing_hook.get("command") == hook["command"]:
                    if existing_hook == hook:
                        return False
                    existing_hook.clear()
                    existing_hook.update(dict(hook))
                    return True
        entries.append({"hooks": [dict(hook)]})
        return True

    def install_auto_repack(self, root: Path) -> dict[str, str]:
        """Install git hooks for auto-repack. Returns results dict."""
        results: dict[str, str] = {}
        results[".codex/hooks.json"] = self.patch_codex_hooks(root)
        hook_results = install_git_hooks(root, agent="auto")
        results.update({f"git:{k}": v for k, v in hook_results.items()})
        return results
