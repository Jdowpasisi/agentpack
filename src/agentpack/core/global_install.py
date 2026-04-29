from __future__ import annotations

import os
import re
import stat
from pathlib import Path

# ---------------------------------------------------------------------------
# Git template hooks — copied into .git/hooks/ on every git init / git clone
# ---------------------------------------------------------------------------

_GIT_TEMPLATE_DIR = Path.home() / ".git-templates"
_AGENTPACK_MARKER = "# agentpack:global"

_POST_CHECKOUT_SCRIPT = """\
#!/bin/sh
# agentpack:global
# Repack only if this repo has already been opted in to agentpack.
[ -f .agentpack/config.toml ] && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &
"""

_POST_COMMIT_SCRIPT = """\
#!/bin/sh
# agentpack:global
# Repack only if this repo has already been opted in to agentpack.
[ -f .agentpack/config.toml ] && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &
"""

_POST_MERGE_SCRIPT = """\
#!/bin/sh
# agentpack:global
# Repack only if this repo has already been opted in to agentpack.
[ -f .agentpack/config.toml ] && agentpack pack --task auto --mode balanced >/dev/null 2>&1 &
"""

_HOOK_SCRIPTS = {
    "post-checkout": _POST_CHECKOUT_SCRIPT,
    "post-commit": _POST_COMMIT_SCRIPT,
    "post-merge": _POST_MERGE_SCRIPT,
}


def install_git_template_hooks(dry_run: bool = False) -> dict[str, str]:
    """Install agentpack hooks into ~/.git-templates/hooks/.

    Git copies these into every new repo on `git init` or `git clone`.
    Returns {hook_name: action}. With dry_run=True, reports what would happen.
    """
    hooks_dir = _GIT_TEMPLATE_DIR / "hooks"
    if not dry_run:
        hooks_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    for name, script in _HOOK_SCRIPTS.items():
        hook_path = hooks_dir / name
        if hook_path.exists():
            content = hook_path.read_text()
            if _AGENTPACK_MARKER in content:
                results[name] = "unchanged"
                continue
            results[name] = "would-append" if dry_run else "appended"
            if not dry_run:
                sep = "" if content.endswith("\n") else "\n"
                hook_path.write_text(content + sep + script)
        else:
            results[name] = "would-create" if dry_run else "created"
            if not dry_run:
                hook_path.write_text(script)
        if not dry_run:
            hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return results


def configure_git_template_dir(dry_run: bool = False) -> str:
    """Set git's global init.templateDir to ~/.git-templates. Returns action taken."""
    if dry_run:
        return "would-configure"
    import subprocess
    result = subprocess.run(
        ["git", "config", "--global", "init.templateDir", str(_GIT_TEMPLATE_DIR)],
        capture_output=True, text=True,
    )
    return "configured" if result.returncode == 0 else "failed"


def remove_git_template_hooks() -> dict[str, str]:
    """Remove agentpack lines from ~/.git-templates/hooks/*."""
    hooks_dir = _GIT_TEMPLATE_DIR / "hooks"
    if not hooks_dir.exists():
        return {}

    results: dict[str, str] = {}
    for name in _HOOK_SCRIPTS:
        hook_path = hooks_dir / name
        if not hook_path.exists():
            continue
        content = hook_path.read_text()
        if _AGENTPACK_MARKER not in content:
            results[name] = "unchanged"
            continue
        # Remove agentpack block (shebang + marker + agentpack lines)
        lines = content.splitlines(keepends=True)
        new_lines: list[str] = []
        skip = False
        for line in lines:
            if _AGENTPACK_MARKER in line:
                skip = True
                # Also remove the preceding shebang if it was the only line before marker
                if new_lines and new_lines[-1].strip().startswith("#!/"):
                    prev = "".join(new_lines[:-1])
                    if not prev.strip():
                        new_lines.pop()
                continue
            if skip:
                if line.startswith("agentpack ") or line.strip() == "":
                    continue
                skip = False
            new_lines.append(line)

        new_content = "".join(new_lines).strip()
        if new_content in ("", "#!/bin/sh", "#!/bin/bash"):
            hook_path.unlink()
            results[name] = "removed"
        else:
            hook_path.write_text(new_content + "\n")
            results[name] = "cleaned"

    return results


# ---------------------------------------------------------------------------
# Shell rc hook — `cd` into any git repo → auto-bootstrap agentpack
# ---------------------------------------------------------------------------

_SHELL_MARKER_START = "# agentpack:chpwd:start"
_SHELL_MARKER_END = "# agentpack:chpwd:end"

_ZSH_HOOK = """\
# agentpack:chpwd:start
_agentpack_chpwd() {
  # Only act on repos explicitly opted in (have .agentpack/config.toml).
  # Does NOT auto-init unknown repos — that's an explicit 'agentpack init' decision.
  if [ -f .agentpack/config.toml ]; then
    agentpack status >/dev/null 2>&1 || agentpack pack --task auto --mode balanced >/dev/null 2>&1 &
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook chpwd _agentpack_chpwd
# agentpack:chpwd:end"""

_BASH_HOOK = """\
# agentpack:chpwd:start
_agentpack_chpwd() {
  # Only act on repos explicitly opted in (have .agentpack/config.toml).
  if [ -f .agentpack/config.toml ]; then
    agentpack status >/dev/null 2>&1 || agentpack pack --task auto --mode balanced >/dev/null 2>&1 &
  fi
}
if [[ "$PROMPT_COMMAND" != *"_agentpack_chpwd"* ]]; then
  PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_agentpack_chpwd"
fi
# agentpack:chpwd:end"""

_BLOCK_RE = re.compile(
    r"# agentpack:chpwd:start.*?# agentpack:chpwd:end\n?",
    re.DOTALL,
)


def _detect_rc_file() -> Path | None:
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    if "bash" in shell:
        rc = Path.home() / ".bashrc"
        profile = Path.home() / ".bash_profile"
        return rc if rc.exists() else profile
    return None


def install_shell_hook(rc_file: Path | None = None, dry_run: bool = False) -> tuple[str, Path | None]:
    """Append agentpack chpwd hook to shell rc. Returns (action, rc_path)."""
    target = rc_file or _detect_rc_file()
    if target is None:
        return "skipped (unknown shell)", None

    shell_hook = _ZSH_HOOK if "zsh" in str(target) else _BASH_HOOK

    if target.exists():
        content = target.read_text()
        if _SHELL_MARKER_START in content:
            new_content = _BLOCK_RE.sub(shell_hook + "\n", content)
            if new_content != content:
                if not dry_run:
                    target.write_text(new_content)
                return "would-update" if dry_run else "updated", target
            return "unchanged", target
        if not dry_run:
            sep = "" if content.endswith("\n") else "\n"
            target.write_text(content + sep + shell_hook + "\n")
        return "would-append" if dry_run else "appended", target
    else:
        if not dry_run:
            target.write_text(shell_hook + "\n")
        return "would-create" if dry_run else "created", target


def remove_shell_hook(rc_file: Path | None = None) -> tuple[str, Path | None]:
    """Remove agentpack chpwd hook from shell rc. Returns (action, rc_path)."""
    target = rc_file or _detect_rc_file()
    if target is None or not target.exists():
        return "unchanged", target

    content = target.read_text()
    if _SHELL_MARKER_START not in content:
        return "unchanged", target

    new_content = _BLOCK_RE.sub("", content)
    target.write_text(new_content)
    return "removed", target
