from __future__ import annotations

from pathlib import Path

import typer

from agentpack.commands._shared import console, _root, run_refresh
from agentpack.commands.install import _install_slash_command
from agentpack.core.context_pack import load_pack_metadata
from agentpack.integrations.agents import (
    SUPPORTED_AGENTS,
    check_agent_integration,
    expand_agents,
    install_agent_integration,
)


def register(app: typer.Typer) -> None:
    @app.command()
    def migrate(
        path: list[Path] = typer.Option(
            None,
            "--path",
            "-p",
            help="Repo root or parent directory. May be provided multiple times.",
        ),
        discover: bool = typer.Option(
            False,
            "--discover",
            help="Scan each path for nested repos instead of treating paths as exact repo roots.",
        ),
        max_depth: int = typer.Option(3, "--max-depth", help="Maximum nested discovery depth."),
        agent: str = typer.Option(
            "auto",
            "--agent",
            help=f"Agent integration to migrate ({' | '.join(SUPPORTED_AGENTS)}).",
        ),
        repair: bool = typer.Option(True, "--repair/--check-only", help="Repair stale/missing integration files."),
        refresh_context: bool = typer.Option(
            False,
            "--refresh-context",
            help="Refresh context packs after repair.",
        ),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show actions without writing files."),
        mode: str = typer.Option("balanced", "--mode", help="Refresh mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Refresh token budget (0 = config default)."),
    ) -> None:
        """Migrate existing repos to current AgentPack guard/freshness integrations."""
        if agent not in SUPPORTED_AGENTS:
            console.print(f"[yellow]Unknown agent: {agent}. Supported: {', '.join(SUPPORTED_AGENTS)}[/]")
            raise typer.Exit(1)
        if mode not in ("minimal", "balanced", "deep"):
            console.print(f"[red]Invalid mode: {mode}. Use minimal|balanced|deep.[/]")
            raise typer.Exit(1)
        if max_depth < 0:
            console.print("[red]--max-depth must be >= 0[/]")
            raise typer.Exit(1)

        roots = _find_repo_roots(path or [_root()], discover=discover, max_depth=max_depth)
        if not roots:
            console.print("[yellow]No AgentPack/git repos found.[/]")
            raise typer.Exit(1)

        ok = True
        console.print(f"[bold]Migrating {len(roots)} repo(s)[/]")
        for repo in roots:
            repo_ok = _migrate_repo(
                repo,
                agent=agent,
                repair=repair,
                refresh_context=refresh_context,
                dry_run=dry_run,
                mode=mode,
                budget=budget,
            )
            ok = ok and repo_ok

        if not ok:
            raise typer.Exit(1)


def _find_repo_roots(paths: list[Path], *, discover: bool, max_depth: int) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        base = raw.expanduser().resolve()
        candidates = _discover_repos(base, max_depth) if discover else [base]
        for candidate in candidates:
            if not _is_repo_like(candidate):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _discover_repos(base: Path, max_depth: int) -> list[Path]:
    if not base.exists() or not base.is_dir():
        return []
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    skip = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__"}
    while stack:
        current, depth = stack.pop()
        if _is_repo_like(current):
            found.append(current)
            continue
        if depth >= max_depth:
            continue
        try:
            children = [child for child in current.iterdir() if child.is_dir() and child.name not in skip]
        except OSError:
            continue
        for child in children:
            stack.append((child, depth + 1))
    return sorted(found)


def _is_repo_like(path: Path) -> bool:
    return path.is_dir() and ((path / ".git").exists() or (path / ".agentpack" / "config.toml").exists())


def _migrate_repo(
    root: Path,
    *,
    agent: str,
    repair: bool,
    refresh_context: bool,
    dry_run: bool,
    mode: str,
    budget: int,
) -> bool:
    console.print(f"\n[bold]{root}[/]")
    try:
        agents = expand_agents(agent, root)
    except Exception as exc:
        console.print(f"  [yellow]![/] Could not resolve agent: {exc}")
        return False

    ok = True
    for selected in agents:
        failing = [check for check in check_agent_integration(root, selected) if not check.ok]
        if failing:
            ok = False
            console.print(f"  [yellow]![/] {selected}: {len(failing)} integration check(s) need repair")
            for check in failing:
                console.print(f"    [dim]- {check.label}: {check.detail}[/]")
            if repair and selected != "generic":
                if dry_run:
                    console.print(f"    [dim]Would repair {selected} integration[/]")
                else:
                    install_agent_integration(
                        root,
                        selected,
                        global_install=False,
                        install_slash_command=_install_slash_command,
                    )
                    after = [check for check in check_agent_integration(root, selected) if not check.ok]
                    if after:
                        console.print(f"    [red]✗[/] repair left {len(after)} failing check(s)")
                    else:
                        console.print("    [green]✓[/] repaired")
                        ok = True
        else:
            console.print(f"  [green]✓[/] {selected}: integration current")

    if refresh_context:
        selected_agent = agents[0] if agents else "generic"
        if dry_run:
            console.print(f"  [dim]Would refresh context for {selected_agent}[/]")
        else:
            stats = run_refresh(root, selected_agent, mode, budget)
            if stats is None:
                ok = False
            else:
                console.print(f"  [green]✓[/] context refreshed ({stats['files']} files)")
    elif not load_pack_metadata(root):
        console.print("  [yellow]![/] no context metadata found; add --refresh-context to generate it")

    return ok or repair
