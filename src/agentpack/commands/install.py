from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentpack.commands._shared import console, _root
from agentpack.integrations.agents import SUPPORTED_AGENTS, install_agent_integration, resolve_agent
from agentpack.integrations.global_install import (
    configure_git_template_dir,
    install_git_template_hooks,
    install_shell_hook,
    remove_git_template_hooks,
    remove_shell_hook,
)


def _installable_agents() -> tuple[str, ...]:
    return tuple(agent for agent in SUPPORTED_AGENTS if agent != "all")


def _resolve_install_agent(agent: str, root: Path) -> str:
    resolved = resolve_agent(agent, root)
    if agent == "auto":
        console.print(f"[dim]Auto-detected agent: {resolved}[/]")
    return resolved


def _validate_install_agent(agent: str) -> None:
    if agent in _installable_agents():
        return
    console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(_installable_agents())}[/]")
    raise typer.Exit(1)


def _print_install_results(agent: str, results: dict[str, str]) -> None:
    if not results:
        console.print("[green]Generic agent selected.[/] No agent-specific hooks are required.")
        console.print("  Write [bold].agentpack/task.md[/], then run [bold]agentpack pack --agent generic --task auto[/] to generate context.")
        return

    for key, action in results.items():
        if action == "unchanged":
            continue
        if key.startswith("git:"):
            console.print(f"[green].git/hooks/{key[4:]} {action}.[/]")
        elif key == "vscode:tasks":
            console.print(f"[green].vscode/tasks.json {action}.[/]")
        elif key == "/agentpack":
            console.print(f"[green]/agentpack slash command {action}.[/]")
        else:
            console.print(f"[green]{key} {action}.[/]")

    if agent in {"cursor", "windsurf", "codex", "generic"}:
        console.print(f"  Write [bold].agentpack/task.md[/], then run [bold]agentpack pack --agent {agent} --task auto[/] to generate context.")
    elif agent == "antigravity":
        console.print("  AgentPack Skill will activate automatically in Antigravity for coding tasks.")


def _print_dry_run_agent(agent: str) -> None:
    if agent == "claude":
        console.print("\n[dim]Would patch: CLAUDE.md, Claude hooks, MCP config, and /agentpack command[/]")
    elif agent == "cursor":
        console.print("\n[dim]Would patch: .cursorrules, .cursor/rules/agentpack.mdc, VS Code task, git hooks[/]")
    elif agent == "windsurf":
        console.print("\n[dim]Would patch: .windsurfrules, VS Code task, git hooks[/]")
    elif agent == "codex":
        console.print("\n[dim]Would patch: AGENTS.md, .codex/hooks.json, git hooks[/]")
    elif agent == "antigravity":
        console.print("\n[dim]Would patch: GEMINI.md, VS Code task, git hooks[/]")
    elif agent == "generic":
        console.print("\n[dim]Would not patch agent files; generic has no agent-specific hooks[/]")


def register(app: typer.Typer) -> None:
    @app.command()
    def install(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Target agent ({' | '.join(_installable_agents())}). auto detects from env/project files.",
        ),
        slash_command: bool = typer.Option(
            True,
            "--slash-command/--no-slash-command",
            help="Install /agentpack slash command (Claude only).",
        ),
        global_install: bool = typer.Option(False, "--global/--local", help="Install globally or locally."),
    ) -> None:
        """Install or refresh one AI-agent integration in the current repo."""
        root = _root()
        _validate_install_agent(agent)
        resolved = _resolve_install_agent(agent, root)
        results = install_agent_integration(
            root,
            resolved,
            global_install=global_install,
            slash_command=slash_command,
            install_slash_command=_install_slash_command,
        )
        _print_install_results(resolved, results)

    @app.command(name="global-install")
    def global_install_cmd(
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Target agent ({' | '.join(_installable_agents())}). auto detects from env/project files.",
        ),
        pipx: bool = typer.Option(True, "--pipx/--no-pipx", help="Install via pipx for global availability."),
        shell_hook: bool = typer.Option(True, "--shell-hook/--no-shell-hook", help="Add cd hook to shell rc for auto-bootstrap."),
        git_template: bool = typer.Option(True, "--git-template/--no-git-template", help="Install git template hooks for every new repo."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be changed without mutating anything."),
    ) -> None:
        """Install global shell/git automation, then refresh the selected agent integration."""
        import subprocess as sp

        if dry_run:
            console.print("[bold yellow]Dry run — no files will be changed.[/]\n")

        if pipx and not dry_run:
            console.print("[bold]Installing agentpack globally via pipx...[/]")
            result = sp.run(
                ["pipx", "install", "agentpack-cli", "--force"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print("[green]agentpack installed globally.[/] Available as `agentpack` in any shell.")
            else:
                console.print("[yellow]pipx install failed. Trying pip install --user...[/]")
                result2 = sp.run(
                    [sys.executable, "-m", "pip", "install", "--user", "agentpack-cli"],
                    capture_output=True,
                    text=True,
                )
                if result2.returncode != 0:
                    console.print(f"[red]Install failed:[/] {result2.stderr[:200]}")
                    raise typer.Exit(1)
                console.print("[green]Installed via pip --user.[/]")
        elif pipx and dry_run:
            console.print("[dim]Would run: pipx install agentpack-cli[/]")

        if git_template:
            console.print("\n[bold]Git template hooks:[/]" if dry_run else "\n[bold]Setting up git template hooks...[/]")
            hook_results = install_git_template_hooks(dry_run=dry_run)
            for name, action in hook_results.items():
                if action != "unchanged":
                    prefix = "[dim]" if dry_run else "[green]"
                    console.print(f"{prefix}~/.git-templates/hooks/{name} {action}.[/]")
            git_cfg_action = configure_git_template_dir(dry_run=dry_run)
            if dry_run:
                console.print(f"[dim]git config --global init.templateDir {git_cfg_action}.[/]")
            else:
                console.print(f"[green]git config --global init.templateDir {git_cfg_action}.[/]")
                console.print("  Every future [bold]git init[/] or [bold]git clone[/] will auto-bootstrap agentpack.")

        if shell_hook:
            console.print("\n[bold]Shell cd hook:[/]" if dry_run else "\n[bold]Setting up shell cd hook...[/]")
            action, rc_path = install_shell_hook(dry_run=dry_run)
            if rc_path:
                prefix = "[dim]" if dry_run else "[green]"
                console.print(f"{prefix}{rc_path} {action}.[/]")
                if not dry_run:
                    console.print("  When you [bold]cd[/] into a repo with [dim].agentpack/config.toml[/], agentpack")
                    console.print("  silently repacks if stale. [dim]Non-configured repos are never touched.[/]")
                    console.print(f"  [dim]Reload with: source {rc_path}[/]")
            else:
                console.print(f"[yellow]Shell hook: {action}[/]")

        root = _root()
        _validate_install_agent(agent)
        resolved = _resolve_install_agent(agent, root)

        if dry_run:
            _print_dry_run_agent(resolved)
            console.print("\n[bold yellow]Dry run complete. Re-run without --dry-run to apply.[/]")
            return

        results = install_agent_integration(
            root,
            resolved,
            global_install=True,
            install_slash_command=_install_slash_command,
        )
        _print_install_results(resolved, results)
        console.print("\n[bold green]Global install complete.[/]")
        console.print("  Git hooks fire on commit/merge/checkout — [bold]only in opted-in repos[/].")
        if shell_hook:
            console.print("  Shell hook repacks on cd — [bold]only in repos with .agentpack/config.toml[/].")
        console.print("  To opt a repo in: [bold]cd repo && agentpack init[/]")

    @app.command(name="global-uninstall")
    def global_uninstall_cmd(
        shell_hook: bool = typer.Option(True, "--shell-hook/--no-shell-hook", help="Remove cd hook from shell rc."),
        git_template: bool = typer.Option(True, "--git-template/--no-git-template", help="Remove git template hooks."),
    ) -> None:
        """Remove agentpack global hooks (git templates + shell rc hook).

        Per-project .agentpack/ directories and agent config files are not touched.
        """
        if git_template:
            console.print("[bold]Removing git template hooks...[/]")
            results = remove_git_template_hooks()
            if results:
                for name, action in results.items():
                    if action != "unchanged":
                        console.print(f"[green]~/.git-templates/hooks/{name} {action}.[/]")
            else:
                console.print("[dim]No git template hooks found.[/]")

        if shell_hook:
            console.print("\n[bold]Removing shell cd hook...[/]")
            action, rc_path = remove_shell_hook()
            if rc_path:
                console.print(f"[green]{rc_path} {action}.[/]")
            else:
                console.print("[dim]No shell hook found (unknown shell).[/]")

        console.print("\n[bold green]Global uninstall complete.[/]")
        console.print("  Per-project [dim].agentpack/[/] directories are untouched.")
        console.print("  To remove from a specific repo: delete [dim].agentpack/[/] and remove agent config.")


def _install_slash_command(root: Path, global_install: bool) -> str:
    import importlib.resources

    commands_dir = Path.home() / ".claude" / "commands" if global_install else root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    dest = commands_dir / "agentpack.md"

    try:
        pkg_files = importlib.resources.files("agentpack") / "data" / "agentpack.md"
        source_text = pkg_files.read_text(encoding="utf-8")
    except Exception:
        source_text = (Path(__file__).parent.parent / "data" / "agentpack.md").read_text(encoding="utf-8")

    existed = dest.exists()
    if existed and dest.read_text(encoding="utf-8") == source_text:
        return "unchanged"
    dest.write_text(source_text, encoding="utf-8")
    return "updated" if existed else "created"
