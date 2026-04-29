from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

from agentpack.core.global_install import (
    _GIT_TEMPLATE_DIR,
    _AGENTPACK_MARKER,
    _SHELL_MARKER_START,
    _HOOK_SCRIPTS,
    _detect_rc_file,
)
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def doctor() -> None:
        """Diagnose agentpack installation state — global hooks, per-repo config, agent setup."""
        ok = True

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
        context_path = root / ".agentpack" / "context.claude.md"
        if not config_path.exists():
            console.print(f"  [yellow]![/] Not initialized in {root} — run: agentpack init")
        else:
            console.print(f"  [green]✓[/] .agentpack/config.toml present")
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
        if claude_settings.exists() or global_claude_settings.exists():
            path = claude_settings if claude_settings.exists() else global_claude_settings
            try:
                import json
                data = json.loads(path.read_text())
                hooks = data.get("hooks", {})
                has_hooks = "UserPromptSubmit" in hooks or "SessionStart" in hooks
                if has_hooks:
                    console.print(f"  [green]✓[/] Claude hooks present in {path}")
                else:
                    console.print(f"  [yellow]![/] Claude hooks missing in {path} — run: agentpack install --agent claude")
            except Exception:
                console.print(f"  [yellow]![/] Could not parse {path}")

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


def _print_summary(ok: bool) -> None:
    console.print("")
    if ok:
        console.print("[bold green]All checks passed.[/]")
    else:
        console.print("[bold yellow]Some checks failed. Run the suggested commands above to fix.[/]")
