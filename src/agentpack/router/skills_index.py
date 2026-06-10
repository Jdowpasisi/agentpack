from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from agentpack.router.models import SkillInventory

INDEX_PATH = ".agentpack/skills_index.json"
ROOT_RULE_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")


class SkillIndexSource(BaseModel):
    configured_path: str
    resolved_path: str
    exists: bool
    file_count: int = 0
    fingerprint: str = ""


class SkillsIndexDocument(BaseModel):
    schema_version: int = 2
    generated_at: str = ""
    configured_paths: list[str] = Field(default_factory=list)
    sources: list[SkillIndexSource] = Field(default_factory=list)
    inventory: SkillInventory = Field(default_factory=SkillInventory)


class SkillsIndexResult(BaseModel):
    path: str
    refreshed: bool
    reason: str
    document: SkillsIndexDocument


def ensure_inventory_index(
    root: Path,
    paths: list[str] | None = None,
    *,
    force: bool = False,
) -> SkillsIndexResult:
    from agentpack.router.discovery import DEFAULT_SKILL_PATHS, discover_inventory

    configured_paths = list(paths or DEFAULT_SKILL_PATHS)
    sources = [_source_fingerprint(root, configured_path) for configured_path in configured_paths]
    current = load_inventory_index_document(root)
    reason = _stale_reason(current, configured_paths, sources, force)
    index_path = root / INDEX_PATH
    if reason:
        inventory = discover_inventory(root, configured_paths)
        document = SkillsIndexDocument(
            generated_at=datetime.now(timezone.utc).isoformat(),
            configured_paths=configured_paths,
            sources=sources,
            inventory=inventory,
        )
        write_inventory_index_document(root, document)
        return SkillsIndexResult(
            path=str(index_path),
            refreshed=True,
            reason=reason,
            document=document,
        )
    return SkillsIndexResult(path=str(index_path), refreshed=False, reason="fresh", document=current)


def load_inventory_index_document(root: Path) -> SkillsIndexDocument | None:
    path = root / INDEX_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if "inventory" not in data:
        try:
            inventory = SkillInventory.model_validate(data)
        except ValidationError:
            return None
        return SkillsIndexDocument(inventory=inventory)
    try:
        return SkillsIndexDocument.model_validate(data)
    except ValidationError:
        return None


def write_inventory_index_document(root: Path, document: SkillsIndexDocument) -> Path:
    path = root / INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = document.model_dump(
        mode="json",
        exclude={
            "inventory": {
                "skills": {"__all__": {"raw_text"}},
                "rules": {"__all__": {"raw_text"}},
            }
        },
    )
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_inventory_index(root: Path) -> SkillInventory | None:
    document = load_inventory_index_document(root)
    return document.inventory if document is not None else None


def write_inventory_index(root: Path, inventory: SkillInventory) -> Path:
    document = SkillsIndexDocument(
        generated_at=datetime.now(timezone.utc).isoformat(),
        inventory=inventory,
    )
    return write_inventory_index_document(root, document)


def inventory_for_route(root: Path, paths: list[str] | None = None) -> SkillInventory:
    return ensure_inventory_index(root, paths).document.inventory


def _stale_reason(
    current: SkillsIndexDocument | None,
    configured_paths: list[str],
    sources: list[SkillIndexSource],
    force: bool,
) -> str:
    if force:
        return "forced"
    if current is None:
        return "missing"
    if not current.configured_paths or not current.sources:
        return "legacy"
    if current.configured_paths != configured_paths:
        return "paths_changed"
    old = [(source.configured_path, source.fingerprint) for source in current.sources]
    new = [(source.configured_path, source.fingerprint) for source in sources]
    if old != new:
        return "fingerprint_changed"
    return ""


def _source_fingerprint(root: Path, configured_path: str) -> SkillIndexSource:
    resolved = _resolve_source_path(root, configured_path)
    files = _tracked_files(root, resolved)
    parts = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        parts.append(f"{_display_path(path, root)}:{stat.st_mtime_ns}:{stat.st_size}")
    return SkillIndexSource(
        configured_path=configured_path,
        resolved_path=str(resolved),
        exists=resolved.exists(),
        file_count=len(files),
        fingerprint="|".join(parts),
    )


def _tracked_files(root: Path, resolved: Path) -> list[Path]:
    files: list[Path] = []
    if resolved.is_dir():
        files.extend(path for path in resolved.rglob("SKILL.md") if path.is_file())
        files.extend(
            path
            for path in resolved.rglob("*.md")
            if path.is_file() and path.name != "SKILL.md"
        )
        files.extend(path for path in resolved.rglob("*.mdc") if path.is_file())
        files.extend(path for path in resolved.rglob("plugin.json") if path.is_file())
    elif resolved.is_file():
        files.append(resolved)
    for filename in ROOT_RULE_FILES:
        candidate = root / filename
        if candidate.exists():
            files.append(candidate)
    return sorted(set(files), key=lambda path: _display_path(path, root))


def _resolve_source_path(root: Path, configured_path: str) -> Path:
    expanded = Path(configured_path).expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)
