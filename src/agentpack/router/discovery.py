from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agentpack.router.models import SkillInventory
from agentpack.router.parser import parse_rule_file, parse_skill_file

DEFAULT_SKILL_PATHS = [
    ".claude/skills",
    "~/.claude/skills",
    "~/.codex/skills",
    "~/.agents/skills",
    ".agentpack/skills",
    ".cursor/rules",
]
ROOT_RULE_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
INDEX_PATH = ".agentpack/skills_index.json"


def discover_inventory(root: Path, paths: list[str] | None = None) -> SkillInventory:
    inventory = SkillInventory()
    for configured_path in paths or DEFAULT_SKILL_PATHS:
        path = _resolve_source_path(root, configured_path)
        if not path.exists():
            continue
        if configured_path.endswith(".cursor/rules") or path.name == "rules" and path.parent.name == ".cursor":
            inventory.rules.extend(_discover_cursor_rules(path, root))
            continue
        inventory.skills.extend(_discover_skills(path, root, configured_path))

    for filename in ROOT_RULE_FILES:
        path = root / filename
        if path.exists():
            inventory.rules.append(parse_rule_file(path, root=root, source=filename, priority=50))

    inventory.skills = _dedupe_by_path(inventory.skills)
    inventory.rules = _dedupe_by_path(inventory.rules)
    return inventory


def load_inventory_index(root: Path) -> SkillInventory | None:
    path = root / INDEX_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SkillInventory.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def write_inventory_index(root: Path, inventory: SkillInventory) -> Path:
    path = root / INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = inventory.model_dump(
        exclude={
            "skills": {"__all__": {"raw_text"}},
            "rules": {"__all__": {"raw_text"}},
        }
    )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def inventory_for_route(root: Path, paths: list[str] | None = None) -> SkillInventory:
    return load_inventory_index(root) or discover_inventory(root, paths)


def _discover_skills(path: Path, root: Path, source: str) -> list:
    candidates: list[Path] = []
    for child in sorted(path.iterdir()):
        if child.is_dir():
            skill_md = child / "SKILL.md"
            if skill_md.exists():
                candidates.append(skill_md)
        elif child.suffix.lower() == ".md":
            candidates.append(child)
    return [parse_skill_file(candidate, root=root, source=source) for candidate in candidates]


def _discover_cursor_rules(path: Path, root: Path) -> list:
    return [
        parse_rule_file(candidate, root=root, source=".cursor/rules", priority=60)
        for candidate in sorted(path.glob("*.mdc"))
    ]


def _resolve_source_path(root: Path, configured_path: str) -> Path:
    expanded = Path(configured_path).expanduser()
    if expanded.is_absolute():
        return expanded
    return root / expanded


def _dedupe_by_path(items: list) -> list:
    seen: set[str] = set()
    result: list = []
    for item in items:
        if item.path in seen:
            continue
        seen.add(item.path)
        result.append(item)
    return result
