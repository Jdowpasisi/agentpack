from __future__ import annotations

import json
import os
import re
import shutil
from importlib import resources
from pathlib import Path

from agentpack import __version__
from agentpack.core.command_surface import fallback_agent_guidance, prompt_quality_guidance, refresh_commands
from agentpack.integrations.git_hooks import install_git_hooks

def _agentpack_block() -> str:
    commands = refresh_commands("codex")
    stale_refresh = "rerun the guard command" if commands.used_guard else "rerun the refresh command"
    thread_line = (
        "\nFor multiple agent threads in one repo, keep legacy global mode unless a thread is explicit. "
        f"Use `{commands.thread_auto}` to write/read `.agentpack/threads/<id>/...` and get overlap warnings."
        if commands.thread_auto
        else ""
    )
    return f"""\
<!-- agentpack:start -->
## AgentPack Context

At the start of every coding task:

1. Write a one-line task summary to `.agentpack/task.md` (overwrite the whole file).
2. Run `{commands.primary}`.
3. Prefer AgentPack MCP if available. MCP is the active path. Call `agentpack_readiness()` to prove live tool exposure, then `agentpack_route_task(task="<task>")` to get files, rules, skills, commands, and safety warnings.
4. Call `agentpack_pack_context(task="<task>")` only when full packed context is needed, or `agentpack_get_context()` for existing task context.
5. If MCP is unavailable, read `.agentpack/context.md`. Treat it as a fallback artifact; if its `agentpack:freshness` block says `refresh_required: true` or the task does not match, {stale_refresh} before using selected files.
6. Use selected files as starting points, but verify with actual code before editing.

When the user switches to a different coding task, update `.agentpack/task.md`, then call MCP again or rerun the refresh command before editing.

{fallback_agent_guidance()}

{prompt_quality_guidance()}{thread_line}
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
            agents_md.write_text(f"{_agentpack_block()}\n")
            return "created"

        content = agents_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_agentpack_block(), content)
            if new_content != content:
                agents_md.write_text(new_content)
                return "updated"
            return "unchanged"

        agents_md.write_text(content.rstrip() + "\n\n" + _agentpack_block() + "\n")
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

    def install_codex_plugin(self, *, codex_home: Path | None = None) -> dict[str, str]:
        """Install AgentPack's thin Codex plugin package into the local Codex cache."""
        source = _codex_plugin_source()
        target = _codex_plugin_target(codex_home)
        action = _copy_tree_if_changed(source, target)
        return {str(target): action}


def _codex_plugin_target(codex_home: Path | None = None) -> Path:
    root = codex_home or Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return root / "plugins" / "cache" / "local" / "agentpack" / __version__


def _codex_plugin_source() -> Path:
    checkout_source = Path(__file__).resolve().parents[3] / "src" / "agentpack" / "data" / "codex_plugin"
    if checkout_source.exists():
        return checkout_source
    return Path(str(resources.files("agentpack").joinpath("data", "codex_plugin")))


def _copy_tree_if_changed(source: Path, target: Path) -> str:
    if not source.exists():
        raise FileNotFoundError(f"AgentPack Codex plugin assets not found: {source}")
    existed = target.exists()
    changed = False
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = source_file.relative_to(source)
        target_file = target / relative
        try:
            current = target_file.read_bytes()
        except OSError:
            current = None
        desired = source_file.read_bytes()
        if current != desired:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(desired)
            changed = True
    if existed:
        _remove_stale_files(source, target)
    elif not target.exists():
        shutil.copytree(source, target)
        changed = True
    if not existed:
        return "created"
    return "updated" if changed else "unchanged"


def _remove_stale_files(source: Path, target: Path) -> None:
    expected = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
    for target_file in sorted((path for path in target.rglob("*") if path.is_file()), reverse=True):
        if target_file.relative_to(target) not in expected:
            target_file.unlink()
    for directory in sorted((path for path in target.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
