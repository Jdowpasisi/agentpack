from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def is_git_repo(root: Path) -> bool:
    out = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    return out is not None and out.strip() == "true"


def changed_files(root: Path) -> set[str]:
    """Unstaged + staged modified/added files."""
    result: set[str] = set()
    for args in [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ]:
        out = _run(args, root)
        if out:
            for line in out.splitlines():
                line = line.strip()
                if line:
                    result.add(line)
    return result


def untracked_files(root: Path) -> set[str]:
    out = _run(["git", "status", "--short"], root)
    result: set[str] = set()
    if not out:
        return result
    for line in out.splitlines():
        if line.startswith("??"):
            result.add(line[3:].strip())
    return result


def recently_modified_files(root: Path, n: int = 20) -> list[str]:
    out = _run(
        ["git", "log", "--diff-filter=M", "--name-only", "--format=", f"-{n}"],
        root,
    )
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def changed_files_since(root: Path, ref: str) -> set[str]:
    """Files changed between ref and HEAD (e.g. ref='HEAD~1', ref='main')."""
    result: set[str] = set()
    out = _run(["git", "diff", "--name-only", ref, "HEAD"], root)
    if out:
        for line in out.splitlines():
            line = line.strip()
            if line:
                result.add(line)
    return result


def infer_task_from_git(root: Path) -> str:
    """Infer a task description from branch name, changed files, and recent commits.

    Priority: branch name (explicit intent) → changed file paths (current work) → recent commit.
    """
    branch: str | None = None
    branch_out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    if branch_out:
        b = branch_out.strip()
        if b and b not in ("HEAD", "main", "master", "develop"):
            slug = b.split("/", 1)[-1]
            branch = slug.replace("-", " ").replace("_", " ")

    # Changed files are the strongest signal for *current* work
    changed = changed_files(root)
    file_topic = _topic_from_paths(changed) if changed else None

    # Fallback: most recent non-merge commit
    commit: str | None = None
    log_out = _run(["git", "log", "--oneline", "-5"], root)
    if log_out:
        for line in log_out.splitlines():
            line = line.strip()
            if not line:
                continue
            msg = line.split(" ", 1)[1] if " " in line else line
            if not msg.lower().startswith("merge "):
                commit = msg
                break

    if branch and file_topic:
        return f"{branch}: {file_topic}"
    if branch:
        return branch
    if file_topic:
        return file_topic
    if commit:
        return commit
    return "general development"


def _topic_from_paths(paths: set[str]) -> str | None:
    """Extract a short topic string from a set of file paths."""
    _SKIP = {"__init__", "index", "main", "mod", "lib", "utils", "helpers", "types", "constants"}
    words: list[str] = []
    for path in sorted(paths):
        parts = Path(path).parts
        # Skip test dirs and generated dirs
        stem = Path(path).stem
        if stem in _SKIP:
            continue
        # Take the most specific meaningful directory + stem
        for part in reversed(parts[:-1]):
            if part not in ("src", "lib", "pkg", "app", "tests", "test", "__pycache__"):
                words.append(part.replace("_", " ").replace("-", " "))
                break
        words.append(stem.replace("_", " ").replace("-", " "))
    if not words:
        return None
    # Deduplicate preserving order, keep up to 5 words
    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
        if len(unique) == 5:
            break
    return ", ".join(unique)
