from __future__ import annotations

import json
import re
from pathlib import Path

from agentpack.core.command_surface import fallback_agent_guidance, prompt_quality_guidance, refresh_commands


def _agentpack_block() -> str:
    commands = refresh_commands("claude")
    thread_line = (
        "\nFor multiple agent threads in one repo, stay in legacy global mode unless a thread is explicit. Use\n"
        f"`{commands.thread_auto}`\n"
        "or pass `thread_id` to AgentPack MCP tools to use `.agentpack/threads/<id>/...` and get overlap warnings."
        if commands.thread_auto
        else ""
    )
    return f"""\
<!-- agentpack:start -->
## AgentPack

AgentPack MCP server is available. For coding tasks in this repository, call the MCP tool
before editing files to get task-relevant context without loading the entire codebase.
Prefer MCP over reading `.agentpack/context*.md` directly because MCP auto-refreshes stale task
and repo-snapshot context before returning.

```
mcp__agentpack__route_task(task="<what you're working on>")
```

When full packed context is needed, call:

```
mcp__agentpack__pack_context(task="<what you're working on>", budget=4000)
```

Executable fallback:

```bash
{commands.primary}
```

Other tools:
- `mcp__agentpack__readiness()` — proves this host exposes AgentPack MCP tools
- `mcp__agentpack__route_task(task)` — files, rules, skills, commands, and safety warnings
- `mcp__agentpack__explain_file(path)` — score breakdown + symbols for a file
- `mcp__agentpack__get_related_files(path)` — import-graph neighbours
- `mcp__agentpack__get_stats()` — token/saving stats for the latest pack
- `mcp__agentpack__get_context()` — read the latest pack; auto-refreshes when task.md or repo snapshot changed
- `mcp__agentpack__refresh()` — refresh using current task.md

If MCP is not available, fall back to the CLI:

```bash
printf '%s\n' "<task>" > .agentpack/task.md
agentpack pack --agent claude --task auto
```

Then read `.agentpack/context.claude.md`.

{fallback_agent_guidance()}

{prompt_quality_guidance()}{thread_line}
<!-- agentpack:end -->"""


_AGENTPACK_BLOCK = _agentpack_block()

_BLOCK_RE = re.compile(
    r"<!-- agentpack:start -->.*?<!-- agentpack:end -->",
    re.DOTALL,
)


class ClaudeInstaller:
    """Configures Claude-specific repo and global files."""

    def patch_claude_md(self, root: Path) -> str:
        """Insert/update AgentPack block in CLAUDE.md. Returns action taken."""
        claude_md = root / "CLAUDE.md"

        if not claude_md.exists():
            claude_md.write_text(f"{_agentpack_block()}\n")
            return "created"

        content = claude_md.read_text()
        if _BLOCK_RE.search(content):
            new_content = _BLOCK_RE.sub(_agentpack_block(), content)
            if new_content != content:
                claude_md.write_text(new_content)
                return "updated"
            return "unchanged"

        claude_md.write_text(content.rstrip() + "\n\n" + _agentpack_block() + "\n")
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

        # SessionStart: delegate to `agentpack hook` CLI subcommand.
        # Clears sentinels so first UserPromptSubmit gets fresh context.
        session_hook_cmd = "agentpack hook --event SessionStart"
        session_start = hooks.setdefault("SessionStart", [])
        # Remove stale agentpack session hooks (old rm -f / session refresh shell commands).
        def _is_stale_session_hook(cmd: str) -> bool:
            return (
                ".context_injected" in cmd and "rm -f" in cmd
            ) or "agentpack session refresh" in cmd
        for entry in session_start:
            entry["hooks"] = [
                h for h in entry.get("hooks", [])
                if not _is_stale_session_hook(h.get("command", ""))
            ]
        session_start[:] = [e for e in session_start if e.get("hooks")]
        already_has_session_hook = any(
            any(h.get("command", "") == session_hook_cmd for h in entry.get("hooks", []))
            for entry in session_start
        )
        if not already_has_session_hook:
            session_start.append({"hooks": [{"type": "command", "command": session_hook_cmd}]})

        # UserPromptSubmit: delegate to `agentpack hook` CLI subcommand.
        # - Reads prompt from stdin, uses it as pack task keyword.
        # - With MCP: emits Option-B hint (task + top files list, ~100 tokens).
        # - Without MCP: emits capped fallback (top files, hard cap 3k chars).
        # - Background repacks when root_hash changes (content-addressed, not mtime).
        hook_cmd = "agentpack hook --event UserPromptSubmit"
        user_prompt = hooks.setdefault("UserPromptSubmit", [])
        # Remove stale agentpack hooks (old injection hooks, old inline MCP reminder).
        def _is_stale_agentpack_hook(cmd: str) -> bool:
            return (
                "context.claude.md" in cmd
                or ".context_injected" in cmd
                or (".mcp_reminded" in cmd and "python3" in cmd)  # old inline python hooks
            )
        for entry in user_prompt:
            entry["hooks"] = [
                h for h in entry.get("hooks", [])
                if not _is_stale_agentpack_hook(h.get("command", ""))
            ]
        user_prompt[:] = [e for e in user_prompt if e.get("hooks")]
        already_has_prompt_hook = any(
            any(h.get("command", "") == hook_cmd for h in entry.get("hooks", []))
            for entry in user_prompt
        )
        if not already_has_prompt_hook:
            user_prompt.append({
                "hooks": [{
                    "type": "command",
                    "command": hook_cmd,
                    "timeout": 5,
                    "statusMessage": "Checking agentpack index...",
                }]
            })

        new_content = json.dumps(existing, indent=2) + "\n"
        if settings_path.exists() and settings_path.read_text() == new_content:
            return "unchanged"
        settings_path.write_text(new_content)
        return "updated"

    def patch_mcp_server(self, root: Path, global_install: bool = False) -> str:
        """Register agentpack MCP server. Returns action taken.

        Local install writes to .mcp.json (Claude Code's standard per-project
        MCP config). Global install writes to ~/.claude/settings.json.
        """
        agentpack_entry = {"command": "agentpack", "args": ["mcp"]}

        if global_install:
            settings_path = Path.home() / ".claude" / "settings.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)

            existing: dict = {}
            if settings_path.exists():
                try:
                    existing = json.loads(settings_path.read_text())
                except json.JSONDecodeError:
                    existing = {}

            mcp_servers = existing.setdefault("mcpServers", {})
            if mcp_servers.get("agentpack") == agentpack_entry:
                return "unchanged"
            mcp_servers["agentpack"] = agentpack_entry
            settings_path.write_text(json.dumps(existing, indent=2) + "\n")
            return "updated"

        # Local install: use .mcp.json (read by Claude Code for project MCP servers)
        mcp_json_path = root / ".mcp.json"

        existing_mcp: dict = {}
        if mcp_json_path.exists():
            try:
                existing_mcp = json.loads(mcp_json_path.read_text())
            except json.JSONDecodeError:
                existing_mcp = {}

        mcp_servers = existing_mcp.setdefault("mcpServers", {})
        if mcp_servers.get("agentpack") == agentpack_entry:
            self._migrate_mcp_from_claude_settings(root)
            return "unchanged"

        mcp_servers["agentpack"] = agentpack_entry
        mcp_json_path.write_text(json.dumps(existing_mcp, indent=2) + "\n")
        self._migrate_mcp_from_claude_settings(root)
        return "updated"

    def _migrate_mcp_from_claude_settings(self, root: Path) -> None:
        """Remove stale mcpServers key from .claude/settings.json if present."""
        settings_path = root / ".claude" / "settings.json"
        if not settings_path.exists():
            return
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            return
        if "mcpServers" not in existing:
            return
        del existing["mcpServers"]
        settings_path.write_text(json.dumps(existing, indent=2) + "\n")
