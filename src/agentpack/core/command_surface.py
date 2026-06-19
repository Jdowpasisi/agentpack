from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable

from agentpack import __version__


@dataclass(frozen=True)
class RefreshCommands:
    primary: str
    context_missing: str
    thread_auto: str | None
    repair: str
    used_guard: bool


def available_cli_commands() -> tuple[str, ...]:
    """Return command names registered by the importable AgentPack CLI."""
    try:
        import typer.main

        from agentpack.cli import app

        click_cmd = typer.main.get_command(app)
        return tuple(sorted(click_cmd.commands))
    except Exception:
        return ()


def has_cli_command(command: str) -> bool:
    return command in available_cli_commands()


def refresh_commands(agent: str = "auto") -> RefreshCommands:
    if has_cli_command("guard"):
        base = f"agentpack guard --agent {agent} --repair-stale --refresh-context"
        return RefreshCommands(
            primary=base,
            context_missing=base,
            thread_auto=f"AGENTPACK_THREAD_ID=<stable-id> {base} --thread auto",
            repair=base,
            used_guard=True,
        )
    pack = f"agentpack pack --agent {agent} --task auto"
    return RefreshCommands(
        primary=pack,
        context_missing='printf "%s\\n" "<task>" > .agentpack/task.md && ' + pack,
        thread_auto=None,
        repair="agentpack repair --agent " + agent if has_cli_command("repair") else pack,
        used_guard=False,
    )


def refresh_command_args(agent: str = "auto", mode: str = "balanced", budget: int = 0) -> list[str]:
    """Return CLI argv parts for refreshing context with the current command surface."""
    if has_cli_command("guard"):
        args = ["guard", "--agent", agent, "--repair-stale", "--refresh-context", "--mode", mode]
    else:
        args = ["pack", "--agent", agent, "--task", "auto", "--mode", mode]
    if budget:
        args.extend(["--budget", str(budget)])
    return args


def fallback_agent_guidance() -> str:
    return (
        "If AgentPack tools are unavailable or context looks stale/wrong-worktree, "
        "do not trust old pack output. Use direct `rg`, PR diff inspection, and target-file reads, "
        "then run focused validation."
    )


def installed_cli_status() -> dict[str, object]:
    binary = shutil.which("agentpack")
    status: dict[str, object] = {
        "agentpack_version": __version__,
        "binary": binary,
        "importable_commands": list(available_cli_commands()),
    }
    if not binary:
        status["available"] = False
        status["repair_command"] = "pipx install agentpack-cli"
        return status
    try:
        version = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        help_result = subprocess.run(
            [binary, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        status["available"] = False
        status["error"] = str(exc)
        status["repair_command"] = "pipx upgrade agentpack-cli"
        return status
    status["available"] = version.returncode == 0
    status["installed_version"] = (version.stdout.strip() or version.stderr.strip())
    status["help_commands"] = _commands_from_help(help_result.stdout + "\n" + help_result.stderr)
    status["repair_command"] = "pipx upgrade agentpack-cli"
    return status


def _commands_from_help(text: str) -> list[str]:
    commands: set[str] = set()
    known = set(available_cli_commands())
    for line in text.splitlines():
        stripped = line.strip().strip("│").strip()
        if not stripped:
            continue
        first = stripped.split()[0].strip("`")
        if first in known:
            commands.add(first)
    return sorted(commands)


def missing_commands(commands: Iterable[str]) -> list[str]:
    available = set(available_cli_commands())
    return sorted({cmd for cmd in commands if cmd and cmd not in available})
