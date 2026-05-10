from __future__ import annotations

import json
import re
from pathlib import Path

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack

AgentPack MCP server is available. For coding tasks in this repository, call the MCP tool
before editing files to get task-relevant context without loading the entire codebase.

```
mcp__agentpack__pack_context(task="<what you're working on>", budget=4000)
```

Other tools:
- `mcp__agentpack__explain_file(path)` — score breakdown + symbols for a file
- `mcp__agentpack__get_related_files(path)` — import-graph neighbours
- `mcp__agentpack__get_stats()` — token/saving stats for the latest pack
- `mcp__agentpack__get_context()` — read the pre-built pack (no repack)
- `mcp__agentpack__refresh()` — refresh using current task.md

If MCP is not available, fall back to the CLI:

```bash
agentpack pack --agent claude --task "<task>"
```

Then read `.agentpack/context.claude.md`.
<!-- agentpack:end -->"""

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

        # SessionStart: delete sentinel + kick off background repack so first prompt
        # gets fresh context without blocking the session.
        # Use session refresh if session exists (respects task.md), else fall back to pack.
        sentinel_cmd = (
            "rm -f .agentpack/.context_injected .agentpack/.mcp_reminded"
            " && ([ -f .agentpack/session.json ]"
            " && agentpack session refresh >/dev/null 2>&1"
            " || agentpack pack --task auto --mode balanced >/dev/null 2>&1) &"
        )
        session_start = hooks.setdefault("SessionStart", [])
        # Replace any stale agentpack session hooks (old cmd only deleted sentinel).
        for entry in session_start:
            entry["hooks"] = [
                h for h in entry.get("hooks", [])
                if not (".context_injected" in h.get("command", "") and "rm -f" in h.get("command", ""))
            ]
        session_start[:] = [e for e in session_start if e.get("hooks")]
        already_has_session_hook = any(
            any(h.get("command", "") == sentinel_cmd for h in entry.get("hooks", []))
            for entry in session_start
        )
        if not already_has_session_hook:
            session_start.append({"hooks": [{"type": "command", "command": sentinel_cmd}]})

        # UserPromptSubmit: tiny MCP reminder — no context injection, no file reads.
        # MCP server handles actual context retrieval on demand (pull-based).
        # Background repack keeps the index fresh for MCP queries.
        mcp_reminder_cmd = (
            "python3 -c \"\n"
            "import json, pathlib, subprocess\n"
            "snap = pathlib.Path('.agentpack/snapshots/latest.json')\n"
            "sentinel = pathlib.Path('.agentpack/.mcp_reminded')\n"
            "current_hash = __import__('hashlib').md5(snap.read_bytes()).hexdigest() if snap.exists() else None\n"
            "reminded_hash = sentinel.read_text().strip() if sentinel.exists() else None\n"
            # Background repack when repo changed since last pack.
            "if current_hash != reminded_hash:\n"
            "    subprocess.Popen(['agentpack', 'pack', '--task', 'auto', '--mode', 'balanced'],\n"
            "                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "    sentinel.write_text(current_hash or '1')\n"
            "    msg = 'AgentPack: repo changed — repacking index. Call agentpack_pack_context(task=\\\"...\\\") for fresh context.'\n"
            "else:\n"
            "    msg = 'AgentPack MCP ready. Call agentpack_pack_context(task=\\\"...\\\") before editing files.'\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',\n"
            "    'additionalContext': msg}}))\n"
            "\""
        )
        user_prompt = hooks.setdefault("UserPromptSubmit", [])
        # Remove stale large-injection hooks (identified by old signature strings).
        for entry in user_prompt:
            entry["hooks"] = [
                h for h in entry.get("hooks", [])
                if "context.claude.md" not in h.get("command", "")
                and ".context_injected" not in h.get("command", "")
            ]
        user_prompt[:] = [e for e in user_prompt if e.get("hooks")]
        already_has_prompt_hook = any(
            any(h.get("command", "") == mcp_reminder_cmd for h in entry.get("hooks", []))
            for entry in user_prompt
        )
        if not already_has_prompt_hook:
            user_prompt.append({
                "hooks": [{
                    "type": "command",
                    "command": mcp_reminder_cmd,
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
