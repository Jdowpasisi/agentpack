from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from agentpack.integrations.global_install import (
    _GIT_TEMPLATE_DIR,
    _AGENTPACK_MARKER,
    _SHELL_MARKER_START,
    _HOOK_SCRIPTS,
    _detect_rc_file,
)
from agentpack.commands._shared import console, _root
from agentpack.core.context_pack import load_pack_metadata
from agentpack.integrations.agents import SUPPORTED_AGENTS, check_agent_integration, expand_agents


def register(app: typer.Typer) -> None:
    @app.command()
    def doctor(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Agent integration to audit ({' | '.join(SUPPORTED_AGENTS)}). Use all for the full matrix.",
        ),
    ) -> None:
        """Diagnose agentpack installation state — global hooks, per-repo config, agent setup."""
        ok = True
        if agent not in SUPPORTED_AGENTS:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)

        # --- CLI binary ---
        console.print("[bold]CLI[/]")
        binary = shutil.which("agentpack")
        if binary:
            try:
                result = subprocess.run(["agentpack", "--version"], capture_output=True, text=True)
                ver = result.stdout.strip() or result.stderr.strip()
                console.print(f"  [green]✓[/] agentpack found at {binary} ({ver})")
            except Exception:
                console.print(f"  [green]✓[/] agentpack found at {binary}")
        else:
            console.print("  [red]✗[/] agentpack not on PATH — run: pipx install agentpack-cli")
            ok = False

        try:
            root = _root()
            warning = _source_checkout_warning(root, Path(__file__), sys.executable, binary)
            if warning:
                console.print(f"  [yellow]![/] {warning}")
                ok = False
        except Exception:
            pass

        # --- Git template hooks ---
        console.print("\n[bold]Git template hooks (~/.git-templates/hooks/)[/]")
        hooks_dir = _GIT_TEMPLATE_DIR / "hooks"
        if not hooks_dir.exists():
            console.print("  [yellow]![/] ~/.git-templates/hooks/ does not exist — run: agentpack global-install")
            ok = False
        else:
            for name in _HOOK_SCRIPTS:
                hook_path = hooks_dir / name
                if hook_path.exists() and _AGENTPACK_MARKER in hook_path.read_text():
                    console.print(f"  [green]✓[/] {name}")
                else:
                    console.print(f"  [red]✗[/] {name} missing — run: agentpack global-install --no-shell-hook --no-pipx")
                    ok = False

        # --- git config init.templateDir ---
        console.print("\n[bold]git config init.templateDir[/]")
        try:
            result = subprocess.run(
                ["git", "config", "--global", "init.templateDir"],
                capture_output=True, text=True,
            )
            configured_dir = result.stdout.strip()
            if configured_dir == str(_GIT_TEMPLATE_DIR):
                console.print(f"  [green]✓[/] init.templateDir = {configured_dir}")
            elif configured_dir:
                console.print(f"  [yellow]![/] init.templateDir = {configured_dir} (not agentpack's dir)")
            else:
                console.print("  [red]✗[/] init.templateDir not set — run: agentpack global-install --no-shell-hook --no-pipx")
                ok = False
        except Exception:
            console.print("  [yellow]![/] Could not check git config")

        # --- Shell hook ---
        console.print("\n[bold]Shell cd hook[/]")
        rc_file = _detect_rc_file()
        if rc_file is None:
            console.print(f"  [yellow]![/] Unknown shell ({os.environ.get('SHELL', 'unset')}) — cannot check")
        elif not rc_file.exists():
            console.print(f"  [red]✗[/] {rc_file} does not exist — run: agentpack global-install --no-git-template --no-pipx")
            ok = False
        elif _SHELL_MARKER_START in rc_file.read_text():
            console.print(f"  [green]✓[/] Hook present in {rc_file}")
        else:
            console.print(f"  [red]✗[/] Hook missing from {rc_file} — run: agentpack global-install --no-git-template --no-pipx")
            ok = False

        # --- Per-repo state ---
        console.print("\n[bold]Per-repo state[/]")
        try:
            root = _root()
        except Exception:
            console.print("  [dim]Not in a git repository[/]")
            _print_summary(ok)
            return

        config_path = root / ".agentpack" / "config.toml"
        if not config_path.exists():
            console.print(f"  [yellow]![/] Not initialized in {root} — run: agentpack init")
        else:
            console.print("  [green]✓[/] .agentpack/config.toml present")
            context_path = _latest_context_path(root)
            if context_path.exists():
                import time
                age = time.time() - context_path.stat().st_mtime
                age_str = f"{int(age // 3600)}h {int((age % 3600) // 60)}m" if age > 3600 else f"{int(age // 60)}m"
                console.print(f"  [green]✓[/] context pack present (age: {age_str})")
            else:
                console.print("  [yellow]![/] No context pack yet — run: agentpack pack --task \"<task>\"")

        # --- Agent-specific config ---
        console.print("\n[bold]Agent config[/]")
        _check_agent_file(root, "CLAUDE.md", "claude")
        _check_agent_file(root, ".cursorrules", "cursor")
        _check_agent_file(root, ".windsurfrules", "windsurf")
        _check_agent_file(root, "AGENTS.md", "codex")

        claude_settings = root / ".claude" / "settings.json"
        global_claude_settings = Path.home() / ".claude" / "settings.json"
        import json as _json
        _local_has_hooks = False
        _global_has_hooks = False

        def _has_stale_hooks(hooks: dict) -> bool:
            """Detect old inline-Python or context-injection hooks that should be upgraded."""
            all_cmds = [
                h.get("command", "")
                for event_hooks in hooks.values()
                for entry in event_hooks
                for h in entry.get("hooks", [])
            ]
            return any(
                "context.claude.md" in cmd
                or ".context_injected" in cmd
                or (".mcp_reminded" in cmd and "python3" in cmd)
                for cmd in all_cmds
            )

        def _has_current_hooks(hooks: dict) -> bool:
            return "agentpack hook" in str(hooks)

        if claude_settings.exists():
            try:
                data = _json.loads(claude_settings.read_text())
                hooks = data.get("hooks", {})
                if "UserPromptSubmit" in hooks or "SessionStart" in hooks:
                    if _has_stale_hooks(hooks):
                        console.print("  [yellow]![/] Claude hooks stale (local) — old injection hook detected. Run: agentpack install --agent claude")
                        ok = False
                    elif _has_current_hooks(hooks):
                        console.print(f"  [green]✓[/] Claude hooks present (local): {claude_settings}")
                    else:
                        console.print(f"  [green]✓[/] Claude hooks present (local): {claude_settings}")
                    _local_has_hooks = True
                else:
                    console.print("  [yellow]![/] Claude hooks missing (local) — run: agentpack install --agent claude")
                    ok = False
            except Exception:
                console.print(f"  [yellow]![/] Could not parse {claude_settings}")
        else:
            console.print("  [dim]-[/] .claude/settings.json not present (run: agentpack install --agent claude)")
        if global_claude_settings.exists():
            try:
                data = _json.loads(global_claude_settings.read_text())
                hooks = data.get("hooks", {})
                if "UserPromptSubmit" in hooks or "SessionStart" in hooks:
                    if _has_stale_hooks(hooks):
                        console.print("  [yellow]![/] Claude hooks stale (global) — old injection hook detected. Run: agentpack install --agent claude --global")
                    else:
                        console.print(f"  [green]✓[/] Claude hooks present (global): {global_claude_settings}")
                    _global_has_hooks = True
                else:
                    console.print("  [yellow]![/] Claude hooks missing (global) — run: agentpack install --agent claude --global")
            except Exception:
                console.print(f"  [yellow]![/] Could not parse {global_claude_settings}")
        else:
            console.print("  [dim]-[/] ~/.claude/settings.json has no agentpack hooks — run: agentpack install --agent claude --global")
        if _local_has_hooks and not _global_has_hooks:
            console.print("  [yellow]![/] Hooks local-only — context won't auto-inject in other repos. Run: agentpack install --agent claude --global")

        # --- MCP server ---
        console.print("\n[bold]MCP server[/]")
        mcp_json = root / ".mcp.json"
        global_claude_settings_for_mcp = Path.home() / ".claude" / "settings.json"
        _local_has_mcp = False
        _global_has_mcp = False
        if mcp_json.exists():
            try:
                mcp_data = _json.loads(mcp_json.read_text())
                if "agentpack" in mcp_data.get("mcpServers", {}):
                    console.print(f"  [green]✓[/] MCP server registered (local): {mcp_json}")
                    _local_has_mcp = True
                else:
                    console.print("  [yellow]![/] .mcp.json exists but agentpack missing — run: agentpack install --agent claude")
            except Exception:
                console.print(f"  [yellow]![/] Could not parse {mcp_json}")
        else:
            console.print("  [dim]-[/] .mcp.json not present (run: agentpack install --agent claude)")
        if global_claude_settings_for_mcp.exists():
            try:
                global_data = _json.loads(global_claude_settings_for_mcp.read_text())
                if "agentpack" in global_data.get("mcpServers", {}):
                    console.print(f"  [green]✓[/] MCP server registered (global): {global_claude_settings_for_mcp}")
                    _global_has_mcp = True
            except Exception:
                pass
        if not _local_has_mcp and not _global_has_mcp:
            console.print("  [yellow]![/] MCP server not registered — mcp__agentpack__* tools unavailable")

        # --- Agent integration matrix ---
        console.print("\n[bold]Agent integration audit[/]")
        agents = expand_agents(agent, root)
        if agent == "auto":
            console.print(f"  [dim]Auto-detected agent: {agents[0]}[/]")
        for selected in agents:
            console.print(f"  [bold]{selected}[/]")
            for check in check_agent_integration(root, selected):
                if check.ok:
                    console.print(f"    [green]✓[/] {check.label}: {check.detail}")
                    continue
                fix = f" — run: {check.fix}" if check.fix else ""
                console.print(f"    [red]✗[/] {check.label}: {check.detail}{fix}")
                ok = False

        # --- Release hygiene ---
        console.print("\n[bold]Release hygiene[/]")
        findings = _release_hygiene_findings(root)
        if findings:
            for finding in findings:
                console.print(f"  [yellow]![/] {finding}")
            ok = False
        else:
            console.print("  [green]✓[/] no generated release-noise files staged or untracked")

        # --- Slash command ---
        console.print("\n[bold]Slash command (/agentpack)[/]")
        local_cmd = root / ".claude" / "commands" / "agentpack.md"
        global_cmd = Path.home() / ".claude" / "commands" / "agentpack.md"
        if local_cmd.exists():
            console.print(f"  [green]✓[/] Slash command installed (local): {local_cmd}")
        else:
            console.print("  [dim]-[/] Slash command not installed locally — run: agentpack install --agent claude")
        if global_cmd.exists():
            console.print(f"  [green]✓[/] Slash command installed (global): {global_cmd}")
        else:
            console.print("  [dim]-[/] Slash command not installed globally — run: agentpack install --agent claude --global")

        _print_summary(ok)


def _check_agent_file(root: Path, filename: str, agent: str) -> None:
    path = root / filename
    if path.exists():
        content = path.read_text()
        if "agentpack" in content.lower():
            console.print(f"  [green]✓[/] {filename} (agentpack configured)")
        else:
            console.print(f"  [dim]-[/] {filename} exists but agentpack not configured — run: agentpack install --agent {agent}")
    else:
        console.print(f"  [dim]-[/] {filename} not present (optional)")


def _latest_context_path(root: Path) -> Path:
    meta = load_pack_metadata(root)
    if meta and meta.get("context_path"):
        candidate = root / str(meta["context_path"])
        if candidate.exists():
            return candidate
    for rel in (
        ".agentpack/context.md",
        ".agentpack/context.claude.md",
        ".agent/skills/agentpack/SKILL.md",
    ):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return root / ".agentpack" / "context.md"


def _source_checkout_warning(
    root: Path,
    package_file: Path,
    executable: str,
    binary: str | None,
) -> str | None:
    source_pkg = root / "src" / "agentpack"
    if not source_pkg.exists():
        return None
    try:
        package_path = package_file.resolve()
        source_path = source_pkg.resolve()
    except OSError:
        return None
    if package_path.is_relative_to(source_path):
        return None
    binary_text = f" via {binary}" if binary else ""
    return (
        "source checkout detected, but CLI imports installed package "
        f"at {package_path}{binary_text}. Use `PYTHONPATH=src python -m agentpack.cli ...` "
        "or install editable with `pip install -e .`."
    )


_RELEASE_NOISE_PREFIXES = (
    ".agent/",
    ".agentpack/",
    ".claude/worktrees/",
    ".codex/",
    ".cursor/",
    ".vscode/",
)
_RELEASE_NOISE_FILES = {".coverage"}


def _release_hygiene_findings(root: Path) -> list[str]:
    """Flag local generated artifacts that should not be staged or released."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["could not inspect git status for release hygiene"]
    if result.returncode != 0:
        return []

    noisy: list[str] = []
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        status = raw[:2].strip() or "modified"
        path = raw[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        norm = path.replace("\\", "/")
        if norm in _RELEASE_NOISE_FILES or any(norm.startswith(prefix) for prefix in _RELEASE_NOISE_PREFIXES):
            noisy.append(f"{status} {norm}")

    if not noisy:
        return []
    sample = ", ".join(noisy[:8])
    extra = f", ... {len(noisy) - 8} more" if len(noisy) > 8 else ""
    return [f"generated/local artifacts present: {sample}{extra}"]


def _print_summary(ok: bool) -> None:
    console.print("")
    if ok:
        console.print("[bold green]All checks passed.[/]")
    else:
        console.print("[bold yellow]Some checks failed. Run the suggested commands above to fix.[/]")
