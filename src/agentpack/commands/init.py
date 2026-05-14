from __future__ import annotations

import sys
from typing import Optional

import typer

from agentpack.core.config import DEFAULT_CONFIG, CONFIG_TEMPLATE
from agentpack.core.ignore import DEFAULT_AGENTIGNORE
from agentpack.commands._shared import console, _root
from agentpack.integrations.agents import install_agent_integration
from agentpack.session.state import load_session, create_session, SESSION_FILE, TASK_FILE

_GITIGNORE_START = "# agentpack:start"
_GITIGNORE_END = "# agentpack:end"


def _repo_gitignore_block(share_cache: bool = False) -> str:
    cache_line = "" if share_cache else ".agentpack/cache/\n"
    return (
        f"{_GITIGNORE_START}\n"
        "# AgentPack generated context/cache (safe to ignore)\n"
        f"{cache_line}"
        ".agentpack/snapshots/\n"
        ".agentpack/context*\n"
        ".agentpack/metrics.jsonl\n"
        ".agentpack/pack_metadata.json\n"
        ".agentpack/activity.log\n"
        ".agentpack/.gitignore\n"
        ".agentpack/.mcp_reminded\n"
        ".agentpack/session.json\n"
        ".agentpack/task.md\n"
        ".agentpack/benchmark_results.jsonl\n"
        ".agent/skills/agentpack/\n"
        f"{_GITIGNORE_END}\n"
    )


def _patch_repo_gitignore(root, share_cache: bool = False) -> str:
    gitignore = root / ".gitignore"
    block = _repo_gitignore_block(share_cache)
    if not gitignore.exists():
        gitignore.write_text(block, encoding="utf-8")
        return "created"

    content = gitignore.read_text(encoding="utf-8")
    start = content.find(_GITIGNORE_START)
    end = content.find(_GITIGNORE_END)
    if start != -1 and end != -1 and end >= start:
        end += len(_GITIGNORE_END)
        replacement = block.rstrip()
        updated = content[:start].rstrip() + "\n\n" + replacement + "\n" + content[end:].lstrip("\n")
        if updated == content:
            return "unchanged"
        gitignore.write_text(updated, encoding="utf-8")
        return "updated"

    prefix = content.rstrip() + "\n\n" if content.strip() else ""
    gitignore.write_text(prefix + block, encoding="utf-8")
    return "updated"


def _install_agent_integration(root, agent: str) -> dict[str, str]:
    """Install repo-local agent integration files after `agentpack init`."""
    return install_agent_integration(root, agent)


def _print_agent_integration_results(results: dict[str, str]) -> None:
    for key, action in results.items():
        if action == "unchanged":
            continue
        if key.startswith("git:"):
            console.print(f"[green].git/hooks/{key[4:]} {action}[/]")
        elif key == "vscode:tasks":
            console.print(f"[green].vscode/tasks.json {action}[/]")
        else:
            console.print(f"[green]{key} {action}[/]")


def register(app: typer.Typer) -> None:
    @app.command()
    def init(
        force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
        mode: Optional[str] = typer.Option(None, "--mode", help="Default pack mode (minimal|balanced|deep)."),
        budget: int = typer.Option(0, "--budget", help="Default token budget (0 = keep default 25000)."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive prompts, use defaults."),
        silent: bool = typer.Option(False, "--silent", help="Suppress all output (for use in hooks/scripts)."),
        share_cache: bool = typer.Option(False, "--share-cache", help="Commit summary cache to git (recommended for teams)."),
        agent: str = typer.Option("auto", "--agent", help="Target agent (auto|claude|cursor|windsurf|codex|antigravity|generic)."),
    ) -> None:
        """Initialize AgentPack in the current directory.

        One-time setup. After this, just run `agentpack watch` — no other commands needed.
        """
        if silent:
            yes = True
            console.quiet = True
        root = _root()
        agentpack_dir = root / ".agentpack"
        agentpack_dir.mkdir(exist_ok=True)
        (agentpack_dir / "snapshots").mkdir(exist_ok=True)
        (agentpack_dir / "cache").mkdir(exist_ok=True)

        gitignore = agentpack_dir / ".gitignore"
        if not gitignore.exists() or force:
            # With --share-cache, cache/ is committed so teammates skip the summarize step
            cache_line = "" if share_cache else ".agentpack/cache/\n"
            gitignore.write_text(
                f"{cache_line}.agentpack/snapshots/\n.agentpack/context.*\n.agentpack/metrics.jsonl\n"
            )
            console.print("[green]Created[/] .agentpack/.gitignore")
            if share_cache:
                console.print("  [dim]cache/ not gitignored — commit it so teammates skip agentpack summarize[/]")
        else:
            console.print("[dim]Skipped[/] .agentpack/.gitignore (exists)")

        gitignore_action = _patch_repo_gitignore(root, share_cache=share_cache)
        if gitignore_action == "created":
            console.print("[green]Created[/] .gitignore [dim](AgentPack generated artifacts ignored)[/]")
        elif gitignore_action == "updated":
            console.print("[green]Updated[/] .gitignore [dim](AgentPack generated artifacts ignored)[/]")
        else:
            console.print("[dim]Skipped[/] .gitignore (AgentPack block unchanged)")

        config_path_file = agentpack_dir / "config.toml"
        if not config_path_file.exists() or force:
            cfg = DEFAULT_CONFIG.model_copy(deep=True)

            # Interactive mode selection
            if not yes and mode is None and sys.stdin.isatty():
                console.print("\n[bold]Choose default pack mode:[/]")
                console.print("  [cyan]1[/] minimal  — changed files + configs only (fastest, fewest tokens)")
                console.print("  [cyan]2[/] balanced — + deps, tests, summaries [bold](recommended)[/]")
                console.print("  [cyan]3[/] deep     — + docs, more full files (most context)")
                choice = typer.prompt("Mode", default="2")
                mode_map = {"1": "minimal", "2": "balanced", "3": "deep",
                            "minimal": "minimal", "balanced": "balanced", "deep": "deep"}
                cfg.context.default_mode = mode_map.get(choice.strip(), "balanced")
            elif mode in ("minimal", "balanced", "deep"):
                cfg.context.default_mode = mode

            if budget > 0:
                cfg.context.default_budget = budget

            config_toml = CONFIG_TEMPLATE.replace(
                'default_mode = "balanced"',
                f'default_mode = "{cfg.context.default_mode}"',
            )
            if budget > 0:
                config_toml = config_toml.replace(
                    "default_budget = 25000",
                    f"default_budget = {cfg.context.default_budget}",
                )
            config_path_file.parent.mkdir(parents=True, exist_ok=True)
            config_path_file.write_text(config_toml)
            console.print(f"[green]Created[/] .agentpack/config.toml  [dim](mode: {cfg.context.default_mode}, budget: {cfg.context.default_budget:,})[/]")
        else:
            console.print("[dim]Skipped[/] .agentpack/config.toml (exists)")

        ignore_path = root / ".agentignore"
        if not ignore_path.exists() or force:
            ignore_path.write_text(DEFAULT_AGENTIGNORE)
            console.print("[green]Created[/] .agentignore")
        else:
            console.print("[dim]Skipped[/] .agentignore (exists)")

        # Bootstrap session so `agentpack watch` works immediately — no separate `session start` needed
        from agentpack.core.config import load_config
        resolved_mode = load_config(root).context.default_mode
        existing_session = load_session(root)
        resolved_agent = agent
        if existing_session is None or force:
            from agentpack.adapters.detect import detect_agent
            resolved_agent = agent if agent != "auto" else detect_agent(root)
            create_session(root, agent=resolved_agent, mode=resolved_mode)
            console.print(f"[green]Created[/] {SESSION_FILE}  [dim]agent={resolved_agent} mode={resolved_mode}[/]")
            console.print(f"[green]Created[/] {TASK_FILE}  [dim]edit to set your task[/]")
        else:
            console.print(f"[dim]Skipped[/] {SESSION_FILE} (exists)")
            if agent == "auto":
                resolved_agent = existing_session.agent

        _print_agent_integration_results(_install_agent_integration(root, resolved_agent))

        console.print("\n[bold green]AgentPack initialized.[/]")
        console.print("Run [bold]agentpack watch[/] to start auto-refreshing context.")
