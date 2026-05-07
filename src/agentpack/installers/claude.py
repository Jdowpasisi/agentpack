from __future__ import annotations

import json
import re
from pathlib import Path

_AGENTPACK_BLOCK = """\
<!-- agentpack:start -->
## AgentPack Context

AgentPack keeps context fresh automatically. When a session is running:

1. Check `.agentpack/session.json` — if `"active": true`, read `.agentpack/context.md`.
2. When the user gives you a new coding task, write a one-line summary to `.agentpack/task.md`.
3. Re-read `.agentpack/context.md` after watch mode refreshes it (a few seconds).
4. Prefer files listed in context, but verify with actual code before editing.

If no session is running, generate context manually:

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
        sentinel_cmd = (
            "rm -f .agentpack/.context_injected"
            " && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &"
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

        # UserPromptSubmit: hash-gated injection.
        # - Always runs `agentpack status` (cheap; uses cached file hashes).
        # - Stale → background repack, no injection this turn.
        # - Fresh + new pack hash → inject once, write hash to sentinel.
        # - Fresh + same hash → skip (already injected this pack version).
        inject_command = (
            "python3 -c \"\n"
            "import hashlib, json, pathlib, subprocess, sys\n"
            "snap = pathlib.Path('.agentpack/snapshots/latest.json')\n"
            "sentinel = pathlib.Path('.agentpack/.context_injected')\n"
            "injected_hash = sentinel.read_text().strip() if sentinel.exists() else None\n"
            "fresh_session = not sentinel.exists()\n"
            # Fast path: compare snapshot hash directly — no subprocess needed.
            # Only skip if snap exists AND matches injected hash (context already in window).
            "current_hash = hashlib.md5(snap.read_bytes()).hexdigest() if snap.exists() else None\n"
            "if current_hash and current_hash == injected_hash:\n"
            "    sys.exit(0)\n"
            # Snapshot changed or missing — need to check/rebuild the pack.
            # fresh_session: sentinel was just cleared by SessionStart hook.
            "ctx = pathlib.Path('.agentpack/context.claude.md')\n"
            "status = subprocess.run(['agentpack', 'status'], capture_output=True, text=True)\n"
            "if status.returncode != 0:\n"
            "    if fresh_session and not ctx.exists():\n"
            # No pack at all on fresh session — sync pack so first prompt has context.
            "        subprocess.run(['agentpack', 'pack', '--task', 'auto', '--mode', 'balanced'],\n"
            "                       capture_output=True)\n"
            "        current_hash = hashlib.md5(snap.read_bytes()).hexdigest() if snap.exists() else None\n"
            "    else:\n"
            # Pack exists but stale — background repack; inject stale pack this turn.
            "        subprocess.Popen(['agentpack', 'pack', '--task', 'auto', '--mode', 'balanced'],\n"
            "                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "if not ctx.exists(): sys.exit(0)\n"
            "content = ctx.read_text()\n"
            "if len(content) > 60000:\n"
            "    lines = content.splitlines(keepends=True)\n"
            "    kept, total, omit_start = [], 0, None\n"
            "    for i, line in enumerate(lines):\n"
            "        if total + len(line) > 60000:\n"
            "            omit_start = i\n"
            "            break\n"
            "        kept.append(line)\n"
            "        total += len(line)\n"
            "    omitted = len(lines) - (omit_start or len(lines))\n"
            "    content = ''.join(kept) + f'\\n\\n... [truncated: {omitted} lines omitted]'\n"
            "sentinel.write_text(current_hash or '1')\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',\n"
            "    'additionalContext': '[agentpack: context injected]\\n\\n' + content}}))\n"
            "\""
        )
        user_prompt = hooks.setdefault("UserPromptSubmit", [])
        # Replace any stale agentpack inject hooks (identified by signature strings).
        for entry in user_prompt:
            entry["hooks"] = [
                h for h in entry.get("hooks", [])
                if "context.claude.md" not in h.get("command", "")
                and ".context_injected" not in h.get("command", "")
            ]
        user_prompt[:] = [e for e in user_prompt if e.get("hooks")]
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
                    "statusMessage": "Checking agentpack context...",
                }]
            })

        new_content = json.dumps(existing, indent=2) + "\n"
        if settings_path.exists() and settings_path.read_text() == new_content:
            return "unchanged"
        settings_path.write_text(new_content)
        return "updated"
