from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


def is_windows(platform: str | None = None) -> bool:
    value = platform or sys.platform
    return value.startswith("win")


def cli_module_argv(*args: str, python_executable: str | None = None) -> list[str]:
    return [python_executable or sys.executable, "-m", "agentpack.cli", *args]


def shell_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def shell_join(argv: list[str]) -> str:
    return " ".join(shell_quote(part) for part in argv)


def powershell_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell_command(argv: list[str]) -> str:
    exe = powershell_quote(argv[0])
    args = " ".join(powershell_quote(arg) for arg in argv[1:])
    return f"& {exe} {args}"


def powershell_start_process(argv: list[str]) -> str:
    exe = powershell_quote(argv[0])
    arg_list = ", ".join(powershell_quote(arg) for arg in argv[1:])
    return f"Start-Process -WindowStyle Hidden -FilePath {exe} -ArgumentList @({arg_list}) | Out-Null"


def detached_popen(argv: list[str], *, cwd: Path | None = None) -> subprocess.Popen[str]:
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd else None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "text": True,
    }
    if is_windows():
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)
