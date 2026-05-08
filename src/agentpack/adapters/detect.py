from __future__ import annotations

import os
from pathlib import Path


def detect_agent(root: Path) -> str:
    """Infer the target agent from environment and project files.

    Priority:
      1. AGENTPACK_AGENT env var (explicit override)
      2. CLAUDECODE / CLAUDE_CODE_ENTRYPOINT env → claude
      3. ANTIGRAVITY env var present → antigravity
      4. .agent/skills/ dir exists → antigravity
      5. GEMINI.md exists → antigravity
      6. OPENAI_CODEX / CODEX_ENVIRONMENT env → codex
      7. .cursor/ dir or .cursorrules exists → cursor
      8. .windsurfrules exists → windsurf
      9. Fallback → claude
    """
    if override := os.environ.get("AGENTPACK_AGENT"):
        return override

    # Claude Code sets CLAUDECODE=1 and CLAUDE_CODE_ENTRYPOINT in its shell env
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"

    if os.environ.get("ANTIGRAVITY"):
        return "antigravity"

    if (root / ".agent" / "skills").is_dir():
        return "antigravity"

    if (root / "GEMINI.md").exists():
        return "antigravity"

    # Codex sets OPENAI_CODEX=1 or CODEX_ENVIRONMENT in its shell env
    if os.environ.get("OPENAI_CODEX") or os.environ.get("CODEX_ENVIRONMENT"):
        return "codex"

    if (root / ".cursor").is_dir() or (root / ".cursorrules").exists():
        return "cursor"

    if (root / ".windsurfrules").exists():
        return "windsurf"

    return "claude"
