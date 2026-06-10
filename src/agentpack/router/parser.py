from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentpack.router.models import RuleArtifact, SideEffectLevel, SkillArtifact

_TOOL_WORDS = ("bash", "git", "pytest", "docker", "aws", "kubectl", "npm", "pnpm", "uv")
_EXTERNAL_WORDS = ("deploy", "send", "delete", "migrate", "cloud", "slack", "email")
_COMMAND_WORDS = ("run", "execute", "test", "pytest", "npm", "docker", "kubectl", "bash")
_FILE_WRITE_WORDS = ("write", "edit", "modify", "patch", "create")
_STOPWORDS = {
    "and", "are", "but", "for", "from", "how", "into", "the", "this", "that",
    "then", "use", "uses", "using", "when", "with", "your",
}


def parse_skill_file(path: Path, *, root: Path | None = None, source: str = "") -> SkillArtifact:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    rel_path = _display_path(path, root)
    name = str(frontmatter.get("name") or _first_h1(body) or _fallback_name(path))
    description = str(frontmatter.get("description") or _first_paragraph(body))
    applies_to_paths = _list_value(frontmatter, "applies_to_paths") or _list_value(frontmatter, "globs")
    explicit_triggers = _list_value(frontmatter, "triggers")

    trigger_text = "\n".join([
        name,
        description,
        _trigger_sections(body),
        path.parent.name,
        path.stem,
    ])
    raw_for_classification = f"{description}\n{body}"

    return SkillArtifact(
        name=name.strip(),
        source=source or _source_for_path(path, root),
        path=rel_path,
        description=description.strip(),
        domains=_normalized_list(frontmatter, "domains") or _normalized_list(frontmatter, "domain"),
        task_types=_normalized_list(frontmatter, "task_types"),
        languages=_normalized_list(frontmatter, "languages"),
        frameworks=_normalized_list(frontmatter, "frameworks"),
        triggers=sorted(
            set(_terms("\n".join([trigger_text, *explicit_triggers])))
            | {item.lower() for item in explicit_triggers}
        ),
        anti_triggers=_normalized_list(frontmatter, "anti_triggers"),
        tools_required=_tools(raw_for_classification),
        side_effect_level=_side_effect_level(raw_for_classification),
        applies_to_paths=applies_to_paths,
        anti_paths=_list_value(frontmatter, "anti_paths"),
        priority=_int_value(frontmatter.get("priority"), default=50),
        confidence_threshold=_float_value(frontmatter.get("confidence_threshold"), default=0.45),
        raw_text=text,
    )


def parse_rule_file(path: Path, *, root: Path | None = None, source: str = "", priority: int = 50) -> RuleArtifact:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    rel_path = _display_path(path, root)
    name = str(frontmatter.get("name") or _first_h1(body) or path.name)
    description = str(frontmatter.get("description") or _first_paragraph(body))
    scopes = _list_value(frontmatter, "globs") or _list_value(frontmatter, "scope_paths")
    always_apply = frontmatter.get("alwaysApply") is True or frontmatter.get("always_apply") is True
    if always_apply and not scopes:
        scopes = ["**/*"]

    return RuleArtifact(
        name=name.strip(),
        source=source or _source_for_path(path, root),
        path=rel_path,
        scope_paths=scopes,
        priority=priority,
        description=description.strip(),
        raw_text=text,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    frontmatter_text = text[4:end]
    body = text[end + 4:].lstrip("\n")
    return _parse_simple_yaml(frontmatter_text), body


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in (">", "|"):
            i += 1
            block: list[str] = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            result[key] = " ".join(part for part in block if part).strip()
            continue
        if value == "":
            i += 1
            items: list[str] = []
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                item = lines[i].strip()
                if item.startswith("- "):
                    items.append(_clean_scalar(item[2:]))
                i += 1
            result[key] = items
            continue
        result[key] = _clean_scalar(value)
        i += 1
    return result


def _clean_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_clean_scalar(part.strip()) for part in inner.split(",")]
    return value.strip("\"'")


def _normalized_list(frontmatter: dict[str, Any], key: str) -> list[str]:
    return [item.lower() for item in _list_value(frontmatter, key)]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_h1(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _first_paragraph(text: str) -> str:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith("#"):
            continue
        if not stripped:
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)
    return " ".join(paragraphs[0]) if paragraphs else ""


def _trigger_sections(text: str) -> str:
    headings = ("when to use", "use this when", "examples", "example")
    lines = text.splitlines()
    captured: list[str] = []
    active = False
    for line in lines:
        lower = line.strip().lower().rstrip(":")
        is_heading = lower.lstrip("# ").strip() in headings or lower.startswith("use this when")
        if is_heading:
            active = True
            captured.append(line)
            continue
        if active and line.startswith("#"):
            active = False
        if active:
            captured.append(line)
    return "\n".join(captured)


def _terms(text: str) -> list[str]:
    terms = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.replace("_", "-"))
        if token.lower() not in _STOPWORDS
    }
    return sorted(terms)


def _tools(text: str) -> list[str]:
    lower = text.lower()
    return [tool for tool in _TOOL_WORDS if re.search(rf"\b{re.escape(tool)}\b", lower)]


def _side_effect_level(text: str) -> SideEffectLevel:
    lower = text.lower()
    if any(re.search(rf"\b{word}\w*\b", lower) for word in _EXTERNAL_WORDS):
        return "external"
    if any(re.search(rf"\b{word}\w*\b", lower) for word in _COMMAND_WORDS):
        return "command"
    if any(re.search(rf"\b{word}\w*\b", lower) for word in _FILE_WRITE_WORDS):
        return "file_write"
    return "none"


def _list_value(frontmatter: dict[str, Any], key: str) -> list[str]:
    value = frontmatter.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
    return []


def _fallback_name(path: Path) -> str:
    if path.name == "SKILL.md":
        return path.parent.name
    return path.stem


def _display_path(path: Path, root: Path | None) -> str:
    try:
        if root is not None:
            return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    return str(path.expanduser())


def _source_for_path(path: Path, root: Path | None) -> str:
    rel = _display_path(path, root)
    if rel.startswith(".cursor/rules/"):
        return ".cursor/rules"
    if rel in {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}:
        return rel
    if rel.endswith("/SKILL.md"):
        return str(Path(rel).parent)
    return str(Path(rel).parent)
