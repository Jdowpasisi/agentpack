from __future__ import annotations

import re
from collections import Counter

from agentpack.core.token_estimator import estimate_tokens


IMPORTANT_PATTERNS = (
    re.compile(r"\b(error|failed|failure|fatal|exception|traceback|panic|segfault)\b", re.I),
    re.compile(r"\b(assert|expected|actual|received)\b", re.I),
    re.compile(r"^(\+|\-|@@|diff --git|--- |\+\+\+ )"),
    re.compile(r"[\w./-]+\.(py|js|ts|tsx|jsx|go|rs|java|cpp|c|h|md):\d+"),
)


def compress_output(content: str, *, kind: str = "auto", max_items: int = 40) -> str:
    """Summarize noisy command output while preserving actionable lines."""
    lines = content.splitlines()
    if not lines:
        return ""
    before_tokens = estimate_tokens(content)
    normalized_kind = kind.lower().strip() or "auto"
    specialized = _specialized_sections(lines, normalized_kind, before_tokens, max_items)
    if specialized is not None:
        return _finalize_summary(specialized, before_tokens, content)
    important: list[str] = []
    seen: set[str] = set()
    repeated = Counter(line.strip() for line in lines if line.strip())
    for line in lines:
        if _is_important(line, kind) and line not in seen:
            important.append(line)
            seen.add(line)
        if len(important) >= max_items:
            break

    if not important:
        important = _sample_edges(lines, max_items=max_items)

    repeated_lines = [(line, count) for line, count in repeated.most_common(10) if count > 1]
    sections = [
        "# AgentPack Output Summary",
        "",
        f"- kind: {normalized_kind}",
        f"- input lines: {len(lines):,}",
        f"- input tokens: {before_tokens:,}",
        "",
        "## Preserved Lines",
        "",
    ]
    sections.extend(important)
    if repeated_lines:
        sections += ["", "## Repeated Lines", ""]
        for line, count in repeated_lines:
            sections.append(f"- {count}x `{_trim(line, 160)}`")
    result = "\n".join(sections).strip() + "\n"
    after_tokens = estimate_tokens(result)
    if after_tokens >= before_tokens:
        return content
    sections.insert(4, f"- output tokens: {after_tokens:,}")
    sections.insert(5, f"- estimated saving: {max(0.0, (1 - after_tokens / before_tokens) * 100):.1f}%")
    return "\n".join(sections).strip() + "\n"


def _specialized_sections(lines: list[str], kind: str, before_tokens: int, max_items: int) -> list[str] | None:
    if kind in {"pytest", "test", "npm", "vitest", "jest"}:
        preserved = _select_unique(
            lines,
            lambda line: bool(re.search(r"\b(FAILED|FAIL|ERROR|Error:|AssertionError|expected|received|\d+ failed|\d+ passed)\b", line, re.I)),
            max_items,
        )
        if not preserved:
            return None
        return _base_sections(kind, lines, before_tokens, "Test Failures", preserved)
    if kind in {"git-diff", "diff", "patch"}:
        preserved = _select_unique(
            lines,
            lambda line: line.startswith(("diff --git", "@@", "+++", "---", "+", "-")),
            max_items,
        )
        if not preserved:
            return None
        return _base_sections(kind, lines, before_tokens, "Diff Hunks", preserved)
    if kind in {"rg", "grep", "search"}:
        preserved = _select_unique(
            lines,
            lambda line: bool(re.search(r"^[\w./-]+:\d+:", line)) or (":" in line and len(line) < 500),
            max_items,
        )
        if not preserved:
            return None
        return _base_sections(kind, lines, before_tokens, "Search Matches", preserved)
    if kind in {"ls", "find", "tree"}:
        preserved = _sample_edges(lines, max_items=max_items)
        return _base_sections(kind, lines, before_tokens, "Listing Sample", preserved)
    return None


def _base_sections(kind: str, lines: list[str], before_tokens: int, title: str, preserved: list[str]) -> list[str]:
    repeated = Counter(line.strip() for line in lines if line.strip())
    sections = [
        "# AgentPack Output Summary",
        "",
        f"- kind: {kind}",
        f"- input lines: {len(lines):,}",
        f"- input tokens: {before_tokens:,}",
        "",
        f"## {title}",
        "",
        *preserved,
    ]
    repeated_lines = [(line, count) for line, count in repeated.most_common(10) if count > 1]
    if repeated_lines:
        sections += ["", "## Repeated Lines", ""]
        for line, count in repeated_lines:
            sections.append(f"- {count}x `{_trim(line, 160)}`")
    return sections


def _select_unique(lines: list[str], predicate, max_items: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if predicate(line) and line not in seen:
            selected.append(line)
            seen.add(line)
        if len(selected) >= max_items:
            break
    return selected


def _finalize_summary(sections: list[str], before_tokens: int, original: str) -> str:
    result = "\n".join(sections).strip() + "\n"
    after_tokens = estimate_tokens(result)
    if after_tokens >= before_tokens:
        return original
    sections.insert(4, f"- output tokens: {after_tokens:,}")
    sections.insert(5, f"- estimated saving: {max(0.0, (1 - after_tokens / before_tokens) * 100):.1f}%")
    return "\n".join(sections).strip() + "\n"


def _is_important(line: str, kind: str) -> bool:
    if any(pattern.search(line) for pattern in IMPORTANT_PATTERNS):
        return True
    if kind in {"pytest", "test", "npm"} and re.search(r"\b(\d+ failed|\d+ passed|FAIL|FAILED|ERROR)\b", line):
        return True
    if kind in {"rg", "grep"} and ":" in line and len(line) < 500:
        return True
    return False


def _sample_edges(lines: list[str], *, max_items: int) -> list[str]:
    if len(lines) <= max_items:
        return lines
    head = max_items // 2
    tail = max_items - head
    return [*lines[:head], f"... {len(lines) - max_items} line(s) omitted ...", *lines[-tail:]]


def _trim(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."
