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


def current_sha(root: Path) -> str | None:
    out = _run(["git", "rev-parse", "HEAD"], root)
    return out.strip() if out else None


def current_branch(root: Path) -> str | None:
    out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    if not out:
        return None
    branch = out.strip()
    return branch if branch and branch != "HEAD" else None


def dirty_files(root: Path) -> set[str]:
    """Tracked and untracked files in git status --short output."""
    out = _run(["git", "status", "--short"], root)
    if not out:
        return set()
    paths: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # Handles ordinary status lines and simple renames.
        raw_path = line[3:].strip() if len(line) > 3 else line
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[1]
        if raw_path:
            paths.add(raw_path)
    return paths


def file_churn_counts(root: Path, max_commits: int = 200) -> dict[str, int]:
    """Return commit count per file from the last max_commits commits.

    Uses a single git log call — O(1) subprocess, not O(n files).
    Returns empty dict if not a git repo or git unavailable.
    """
    out = _run(
        ["git", "log", "--name-only", "--format=", f"-{max_commits}"],
        root,
    )
    if not out:
        return {}
    counts: dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def staged_files(root: Path) -> set[str]:
    """Files staged for commit (git index only)."""
    out = _run(["git", "diff", "--cached", "--name-only"], root)
    if not out:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def infer_task_with_source(root: Path) -> tuple[str, str]:
    """Infer task description with the heuristic that fired.

    Priority (strongest → weakest):
      branch+staged    staged files present + branch name
      staged           staged files, no branch
      branch+unstaged  unstaged changes + branch name
      branch+commit    branch + latest commit message
      branch           branch name alone
      unstaged         unstaged changes, no branch
      commits          recent commit messages
      recently_modified git log history (noisy — last resort)
      fallback         "general development"
    """
    if not is_git_repo(root):
        return "general development", "fallback"

    staged = staged_files(root)

    unstaged_out = _run(["git", "diff", "--name-only"], root)
    unstaged: set[str] = set()
    if unstaged_out:
        for line in unstaged_out.splitlines():
            line = line.strip()
            if line:
                unstaged.add(line)

    staged_topic = _topic_from_paths(staged) if staged else None
    unstaged_topic = _topic_from_paths(unstaged) if unstaged else None

    branch: str | None = None
    branch_out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    if branch_out:
        b = branch_out.strip()
        if b and b not in ("HEAD", "main", "master", "develop"):
            slug = b.split("/", 1)[-1]
            branch = slug.replace("-", " ").replace("_", " ")

    commit_msgs: list[str] = []
    log_out = _run(["git", "log", "--oneline", "-10"], root)
    if log_out:
        for line in log_out.splitlines():
            line = line.strip()
            if not line:
                continue
            msg = line.split(" ", 1)[1] if " " in line else line
            if not msg.lower().startswith("merge "):
                commit_msgs.append(msg)
            if len(commit_msgs) == 3:
                break

    if branch and staged_topic:
        return f"{branch}: {staged_topic}", "branch+staged"
    if staged_topic:
        return staged_topic, "staged"
    if branch and unstaged_topic:
        return f"{branch}: {unstaged_topic}", "branch+unstaged"
    if branch and commit_msgs:
        return f"{branch}: {commit_msgs[0]}", "branch+commit"
    if branch:
        return branch, "branch"
    if unstaged_topic and commit_msgs:
        return f"{unstaged_topic}: {commit_msgs[0]}", "unstaged+commit"
    if unstaged_topic:
        return unstaged_topic, "unstaged"
    if commit_msgs:
        return "; ".join(commit_msgs[:2]), "commits"

    # Last resort: historical git log — only fires when no live signal found
    recent = recently_modified_files(root, n=10)
    recent_topic = _topic_from_paths(set(recent)) if recent else None
    if recent_topic:
        return recent_topic, "recently_modified"

    return "general development", "fallback"


def infer_task_from_git(root: Path) -> str:
    """Infer a task description from git state. See infer_task_with_source for priority chain."""
    task, _ = infer_task_with_source(root)
    return task


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
