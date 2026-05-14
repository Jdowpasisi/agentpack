from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agentpack.installers.antigravity import AntigravityInstaller
from agentpack.installers.claude import ClaudeInstaller
from agentpack.installers.codex import CodexInstaller
from agentpack.installers.cursor import CursorInstaller
from agentpack.installers.windsurf import WindsurfInstaller

SUPPORTED_AGENTS = ("auto", "all", "claude", "cursor", "windsurf", "codex", "antigravity", "generic")
CONCRETE_AGENTS = ("claude", "cursor", "windsurf", "codex", "antigravity", "generic")
GIT_REPACK_AGENTS = {"cursor", "windsurf", "codex", "antigravity"}
GIT_HOOK_EVENTS = ("post-commit", "post-merge", "post-checkout")


@dataclass(frozen=True)
class AgentCheck:
    agent: str
    label: str
    ok: bool
    detail: str
    fix: str | None = None


def resolve_agent(agent: str, root: Path) -> str:
    if agent != "auto":
        return agent
    from agentpack.adapters.detect import detect_agent

    return detect_agent(root)


def expand_agents(agent: str, root: Path) -> tuple[str, ...]:
    resolved = resolve_agent(agent, root)
    if resolved == "all":
        return CONCRETE_AGENTS
    return (resolved,)


def install_agent_integration(
    root: Path,
    agent: str,
    *,
    global_install: bool = False,
    slash_command: bool = True,
    install_slash_command=None,
) -> dict[str, str]:
    """Install or repair one agent integration and return file/action results."""
    if agent == "claude":
        installer = ClaudeInstaller()
        results = {
            "CLAUDE.md": installer.patch_claude_md(root),
            "~/.claude/settings.json" if global_install else ".claude/settings.json": installer.patch_claude_settings(
                root, global_install
            ),
            "~/.claude/settings.json:mcpServers.agentpack" if global_install else ".mcp.json:mcpServers.agentpack": installer.patch_mcp_server(
                root, global_install
            ),
        }
        if slash_command and install_slash_command is not None:
            results["/agentpack"] = install_slash_command(root, global_install)
        return results

    if agent == "cursor":
        installer = CursorInstaller()
        results = {
            ".cursorrules": installer.patch_cursor_rules(root),
            ".cursor/rules/agentpack.mdc": installer.patch_cursor_mdc(root),
        }
        if not global_install:
            results.update(installer.install_auto_repack(root))
        return results

    if agent == "windsurf":
        installer = WindsurfInstaller()
        results = {".windsurfrules": installer.patch_windsurfrules(root)}
        if not global_install:
            results.update(installer.install_auto_repack(root))
        return results

    if agent == "codex":
        installer = CodexInstaller()
        results = {"AGENTS.md": installer.patch_agents_md(root)}
        if not global_install:
            results.update(installer.install_auto_repack(root))
        return results

    if agent == "antigravity":
        installer = AntigravityInstaller()
        results = {"GEMINI.md": installer.patch_gemini_md(root)}
        if not global_install:
            results.update(installer.install_auto_repack(root))
        return results

    if agent == "generic":
        return {}

    raise ValueError(f"Unknown agent: {agent}")


def check_agent_integration(root: Path, agent: str) -> list[AgentCheck]:
    if agent == "claude":
        return _check_claude(root)
    if agent == "cursor":
        return [
            _file_contains(root, agent, ".cursorrules", "agentpack", "agentpack repair --agent cursor"),
            _file_contains(root, agent, ".cursor/rules/agentpack.mdc", "agentpack", "agentpack repair --agent cursor"),
            *_check_git_hooks(root, agent),
            _file_contains(root, agent, ".vscode/tasks.json", "agentpack", "agentpack repair --agent cursor"),
        ]
    if agent == "windsurf":
        return [
            _file_contains(root, agent, ".windsurfrules", "agentpack", "agentpack repair --agent windsurf"),
            *_check_git_hooks(root, agent),
            _file_contains(root, agent, ".vscode/tasks.json", "agentpack", "agentpack repair --agent windsurf"),
        ]
    if agent == "codex":
        return [
            _file_contains(root, agent, "AGENTS.md", "agentpack", "agentpack repair --agent codex"),
            _codex_hooks(root),
            *_check_git_hooks(root, agent),
        ]
    if agent == "antigravity":
        return [
            _file_contains(root, agent, "GEMINI.md", "agentpack", "agentpack repair --agent antigravity"),
            *_check_git_hooks(root, agent),
            _file_contains(root, agent, ".vscode/tasks.json", "agentpack", "agentpack repair --agent antigravity"),
        ]
    if agent == "generic":
        return [AgentCheck(agent, "generic", True, "no agent-specific files required")]
    raise ValueError(f"Unknown agent: {agent}")


def _file_contains(root: Path, agent: str, rel: str, needle: str, fix: str) -> AgentCheck:
    path = root / rel
    if not path.exists():
        return AgentCheck(agent, rel, False, "missing", fix)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return AgentCheck(agent, rel, False, "unreadable", fix)
    if needle.lower() in content.lower():
        return AgentCheck(agent, rel, True, "configured")
    return AgentCheck(agent, rel, False, "present but AgentPack block missing", fix)


def _check_git_hooks(root: Path, agent: str) -> list[AgentCheck]:
    checks: list[AgentCheck] = []
    for event in GIT_HOOK_EVENTS:
        path = root / ".git" / "hooks" / event
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                content = ""
            if "agentpack:auto-repack" in content:
                checks.append(AgentCheck(agent, f".git/hooks/{event}", True, "auto-repack hook present"))
                continue
        checks.append(AgentCheck(agent, f".git/hooks/{event}", False, "missing auto-repack hook", f"agentpack repair --agent {agent}"))
    return checks


def _check_claude(root: Path) -> list[AgentCheck]:
    checks = [_file_contains(root, "claude", "CLAUDE.md", "agentpack", "agentpack repair --agent claude")]
    settings = root / ".claude" / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            checks.append(AgentCheck("claude", ".claude/settings.json", False, "invalid JSON", "agentpack repair --agent claude"))
        else:
            hooks_text = json.dumps(data.get("hooks", {}))
            ok = (
                "agentpack hook --event SessionStart" in hooks_text
                and "agentpack hook --event UserPromptSubmit" in hooks_text
            )
            checks.append(
                AgentCheck(
                    "claude",
                    ".claude/settings.json",
                    ok,
                    "current hooks present" if ok else "missing current lifecycle hooks",
                    None if ok else "agentpack repair --agent claude",
                )
            )
    else:
        checks.append(AgentCheck("claude", ".claude/settings.json", False, "missing", "agentpack repair --agent claude"))

    mcp = root / ".mcp.json"
    if mcp.exists():
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            checks.append(AgentCheck("claude", ".mcp.json", False, "invalid JSON", "agentpack repair --agent claude"))
        else:
            ok = data.get("mcpServers", {}).get("agentpack") == {"command": "agentpack", "args": ["mcp"]}
            checks.append(
                AgentCheck(
                    "claude",
                    ".mcp.json",
                    ok,
                    "MCP server registered" if ok else "agentpack MCP server missing",
                    None if ok else "agentpack repair --agent claude",
                )
            )
    else:
        checks.append(AgentCheck("claude", ".mcp.json", False, "missing", "agentpack repair --agent claude"))
    return checks


def _codex_hooks(root: Path) -> AgentCheck:
    path = root / ".codex" / "hooks.json"
    if not path.exists():
        return AgentCheck("codex", ".codex/hooks.json", False, "missing Codex app lifecycle hooks", "agentpack repair --agent codex")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return AgentCheck("codex", ".codex/hooks.json", False, "invalid JSON", "agentpack repair --agent codex")
    text = json.dumps(data.get("hooks", {}))
    ok = (
        "agentpack hook --event SessionStart" in text
        and "agentpack hook --event UserPromptSubmit" in text
    )
    return AgentCheck(
        "codex",
        ".codex/hooks.json",
        ok,
        "Codex app lifecycle hooks present" if ok else "missing SessionStart/UserPromptSubmit hooks",
        None if ok else "agentpack repair --agent codex",
    )
