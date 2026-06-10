# Automatic Skills Index and Dashboard Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make skills inventory automatic and freshness-aware across existing AgentPack surfaces, then show discovered skill directories, domains, tags, side effects, and metadata quality in the dashboard without requiring developers to run a new command.

**Architecture:** Keep `agentpack skills index` as a manual repair/debug command, but move normal indexing behind a shared `ensure_inventory_index()` helper used by routing, dashboard, and next-step recommendations. Store metadata-only index documents with source fingerprints so added, removed, or modified skill files are picked up lazily by the next consumer command.

**Tech Stack:** Python 3.10+, Pydantic, pathlib, JSON, existing `agentpack.router.discovery`, existing dashboard snapshot/rendering, pytest.

---

## File Structure

- Create `src/agentpack/router/skills_index.py`
  - Own index freshness fingerprints, metadata-only index document shape, backward-compatible loading, and `ensure_inventory_index()`.
- Modify `src/agentpack/router/discovery.py`
  - Delegate `load_inventory_index`, `write_inventory_index`, and `inventory_for_route` to the new shared helper while preserving existing imports.
- Modify `src/agentpack/commands/skills.py`
  - Make `skills index` call `ensure_inventory_index(force=True)`.
  - Keep `skills scan` as live discovery without writing.
- Modify `src/agentpack/dashboard/models.py`
  - Add `SkillsInventorySummary`, source/domain summaries, and row models.
- Modify `src/agentpack/dashboard/collectors.py`
  - Call `ensure_inventory_index()` and normalize inventory metadata into the dashboard snapshot.
- Modify `src/agentpack/dashboard/renderers.py`
  - Render a collapsed-by-default style summary table without skill bodies.
- Modify `src/agentpack/commands/next_cmd.py`
  - Recommend repair when automatic skills index refresh fails.
- Modify `src/agentpack/router/service.py`
  - Route through `inventory_for_route()` after it becomes freshness-aware.
- Modify `tests/test_router_discovery.py`
  - Cover freshness rebuilds and backwards-compatible old index reads.
- Modify `tests/test_route_command.py`
  - Keep existing index tests green and add a stale-index route test.
- Modify `tests/test_dashboard_collectors.py`
  - Cover dashboard skills inventory collection.
- Modify `tests/test_dashboard_renderer.py`
  - Cover dashboard skills inventory rendering and no raw body leakage.
- Modify `tests/test_next_command.py`
  - Cover index refresh failure recommendation.

## Task 1: Add Freshness-Aware Skills Index Core

**Files:**
- Create `src/agentpack/router/skills_index.py`
- Modify `tests/test_router_discovery.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_router_discovery.py`:

```python
import json

from agentpack.router.discovery import INDEX_PATH
from agentpack.router.skills_index import ensure_inventory_index, load_inventory_index_document


def test_ensure_inventory_index_rebuilds_when_skill_file_changes(tmp_path):
    skill = tmp_path / ".agentpack" / "skills" / "pytest-debugging" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: pytest-debugging\ntask_types: [testing]\nlanguages: [python]\n---\n\nUse for pytest failures.\n",
        encoding="utf-8",
    )

    first = ensure_inventory_index(tmp_path, paths=[".agentpack/skills"])
    assert first.refreshed is True
    assert [item.name for item in first.document.inventory.skills] == ["pytest-debugging"]

    skill.write_text(
        "---\nname: pytest-debugging\ntask_types: [testing]\nlanguages: [python]\nframeworks: [pytest]\n---\n\nUse for pytest failures.\n",
        encoding="utf-8",
    )
    second = ensure_inventory_index(tmp_path, paths=[".agentpack/skills"])

    assert second.refreshed is True
    assert second.reason == "fingerprint_changed"
    assert second.document.inventory.skills[0].frameworks == ["pytest"]


def test_ensure_inventory_index_reuses_fresh_index(tmp_path):
    skill = tmp_path / ".agentpack" / "skills" / "docs" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Docs\n\nUse for documentation updates.\n", encoding="utf-8")

    first = ensure_inventory_index(tmp_path, paths=[".agentpack/skills"])
    second = ensure_inventory_index(tmp_path, paths=[".agentpack/skills"])

    assert first.refreshed is True
    assert second.refreshed is False
    assert second.reason == "fresh"


def test_load_inventory_index_document_accepts_old_inventory_shape(tmp_path):
    path = tmp_path / INDEX_PATH
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "skills": [
                    {
                        "name": "legacy",
                        "source": ".agentpack/skills",
                        "path": ".agentpack/skills/legacy/SKILL.md",
                    }
                ],
                "rules": [],
            }
        ),
        encoding="utf-8",
    )

    document = load_inventory_index_document(tmp_path)

    assert document is not None
    assert document.inventory.skills[0].name == "legacy"
    assert document.sources == []
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_router_discovery.py::test_ensure_inventory_index_rebuilds_when_skill_file_changes tests/test_router_discovery.py::test_ensure_inventory_index_reuses_fresh_index tests/test_router_discovery.py::test_load_inventory_index_document_accepts_old_inventory_shape -q
```

Expected: fail because `agentpack.router.skills_index` does not exist.

- [ ] **Step 3: Implement `skills_index.py`**

Create `src/agentpack/router/skills_index.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agentpack.router.models import SkillInventory

INDEX_PATH = ".agentpack/skills_index.json"
SKILL_FILENAMES = {"SKILL.md"}
RULE_SUFFIXES = {".mdc"}
ROOT_RULE_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}


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


def ensure_inventory_index(root: Path, paths: list[str] | None = None, *, force: bool = False) -> SkillsIndexResult:
    from agentpack.router.discovery import DEFAULT_SKILL_PATHS, discover_inventory

    configured = list(paths or DEFAULT_SKILL_PATHS)
    sources = [_source_fingerprint(root, configured_path) for configured_path in configured]
    current = load_inventory_index_document(root)
    reason = _stale_reason(current, configured, sources, force)
    index_path = root / INDEX_PATH
    if reason:
        inventory = discover_inventory(root, configured)
        document = SkillsIndexDocument(
            generated_at=datetime.now(timezone.utc).isoformat(),
            configured_paths=configured,
            sources=sources,
            inventory=inventory,
        )
        write_inventory_index_document(root, document)
        return SkillsIndexResult(path=str(index_path), refreshed=True, reason=reason, document=document)
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
    configured: list[str],
    sources: list[SkillIndexSource],
    force: bool,
) -> str:
    if force:
        return "forced"
    if current is None:
        return "missing"
    if current.configured_paths and current.configured_paths != configured:
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
        display = _display_path(path, root)
        parts.append(f"{display}:{stat.st_mtime_ns}:{stat.st_size}")
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
        files.extend(path for path in resolved.rglob("*.md") if path.is_file() and path.name != "SKILL.md")
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
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_router_discovery.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/router/skills_index.py tests/test_router_discovery.py
git commit -m "feat: add freshness-aware skills index"
```

## Task 2: Route and Skills Commands Use Automatic Indexing

**Files:**
- Modify `src/agentpack/router/discovery.py`
- Modify `src/agentpack/commands/skills.py`
- Modify `tests/test_route_command.py`

- [ ] **Step 1: Add route stale-index test**

Append to `tests/test_route_command.py`:

```python
def test_route_refreshes_stale_skills_index(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skill = tmp_path / ".agentpack" / "skills" / "pytest-debugging" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Pytest Debugging\n\nUse for pytest failures.\n", encoding="utf-8")
    runner = CliRunner()

    index = runner.invoke(app, ["skills", "index"])
    assert index.exit_code == 0, index.output

    skill.write_text("# Pytest Debugging\n\nUse for pytest failures and regression tests.\n", encoding="utf-8")
    result = runner.invoke(app, ["route", "--task", "fix pytest regression", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = [item["skill"]["name"] for item in payload["selected_skills"]]
    assert "Pytest Debugging" in names
```

- [ ] **Step 2: Patch `discovery.py` as compatibility wrapper**

Modify imports and functions in `src/agentpack/router/discovery.py`:

```python
from agentpack.router.skills_index import (
    INDEX_PATH,
    inventory_for_route,
    load_inventory_index,
    write_inventory_index,
)
```

Delete the old local implementations of `INDEX_PATH`, `load_inventory_index`, `write_inventory_index`, and `inventory_for_route`. Keep `DEFAULT_SKILL_PATHS`, `discover_inventory()`, and discovery helpers in this file.

- [ ] **Step 3: Patch `skills index`**

Modify `src/agentpack/commands/skills.py`:

```python
from agentpack.router.skills_index import ensure_inventory_index
```

Replace `index_skills()` body with:

```python
root = _root()
cfg = load_config(root)
result = ensure_inventory_index(root, cfg.skills.paths, force=True)
inventory = result.document.inventory
console.print(
    f"Indexed {len(inventory.skills)} skills and {len(inventory.rules)} rules at {result.path}"
)
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_router_discovery.py tests/test_route_command.py tests/test_router_scoring.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/router/discovery.py src/agentpack/commands/skills.py tests/test_route_command.py
git commit -m "feat: auto-refresh skills index for routing"
```

## Task 3: Dashboard Skills Inventory Snapshot

**Files:**
- Modify `src/agentpack/dashboard/models.py`
- Modify `src/agentpack/dashboard/collectors.py`
- Modify `tests/test_dashboard_collectors.py`

- [ ] **Step 1: Add collector test**

Append to `tests/test_dashboard_collectors.py`:

```python
def test_project_dashboard_collects_skills_inventory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    skill = tmp_path / ".agentpack" / "skills" / "pytest-debugging" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: pytest-debugging\n"
        "task_types: [testing]\n"
        "languages: [python]\n"
        "frameworks: [pytest]\n"
        "---\n\n"
        "Use for pytest failures.\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.skills_inventory.total_skills == 1
    assert snapshot.skills_inventory.total_rules == 0
    assert snapshot.skills_inventory.domains[0].name == "testing"
    assert snapshot.skills_inventory.rows[0].name == "pytest-debugging"
    assert snapshot.skills_inventory.rows[0].domains == ["testing"]
    assert snapshot.skills_inventory.rows[0].metadata_quality == "explicit"
    assert snapshot.skills_inventory.index_refreshed is True
```

- [ ] **Step 2: Add models**

Add to `src/agentpack/dashboard/models.py`:

```python
class SkillInventorySourceSummary(BaseModel):
    configured_path: str
    resolved_path: str
    exists: bool
    file_count: int = 0


class SkillDomainSummary(BaseModel):
    name: str
    count: int


class SkillInventoryRow(BaseModel):
    name: str
    path: str
    source: str
    domains: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    side_effect_level: str = ""
    metadata_quality: str = "inferred"


class SkillsInventorySummary(BaseModel):
    available: bool = False
    index_refreshed: bool = False
    index_reason: str = ""
    index_error: str = ""
    total_skills: int = 0
    total_rules: int = 0
    uncategorized_count: int = 0
    missing_metadata_count: int = 0
    duplicate_names: list[str] = Field(default_factory=list)
    sources: list[SkillInventorySourceSummary] = Field(default_factory=list)
    domains: list[SkillDomainSummary] = Field(default_factory=list)
    rows: list[SkillInventoryRow] = Field(default_factory=list)
```

Add `skills_inventory: SkillsInventorySummary = Field(default_factory=SkillsInventorySummary)` to `DashboardSnapshot`.

- [ ] **Step 3: Collect inventory**

In `src/agentpack/dashboard/collectors.py`, import `load_config`, `ensure_inventory_index`, and new models. Add:

```python
def _skills_inventory_summary(root: Path) -> SkillsInventorySummary:
    try:
        cfg = load_config(root)
        result = ensure_inventory_index(root, cfg.skills.paths)
    except Exception as exc:
        return SkillsInventorySummary(index_error=str(exc))
    inventory = result.document.inventory
    rows = [_skill_inventory_row(skill) for skill in inventory.skills]
    domains = _domain_counts(rows)
    names: dict[str, int] = {}
    for row in rows:
        key = row.name.lower()
        names[key] = names.get(key, 0) + 1
    return SkillsInventorySummary(
        available=True,
        index_refreshed=result.refreshed,
        index_reason=result.reason,
        total_skills=len(inventory.skills),
        total_rules=len(inventory.rules),
        uncategorized_count=sum(1 for row in rows if row.domains == ["uncategorized"]),
        missing_metadata_count=sum(1 for row in rows if row.metadata_quality == "inferred"),
        duplicate_names=sorted(name for name, count in names.items() if count > 1),
        sources=[
            SkillInventorySourceSummary(
                configured_path=source.configured_path,
                resolved_path=source.resolved_path,
                exists=source.exists,
                file_count=source.file_count,
            )
            for source in result.document.sources
        ],
        domains=domains,
        rows=rows[:100],
    )


def _skill_inventory_row(skill) -> SkillInventoryRow:
    domains = skill.task_types or skill.frameworks or skill.languages or ["uncategorized"]
    metadata_quality = "explicit" if skill.task_types or skill.languages or skill.frameworks else "inferred"
    return SkillInventoryRow(
        name=skill.name,
        path=skill.path,
        source=skill.source,
        domains=domains,
        languages=skill.languages,
        frameworks=skill.frameworks,
        side_effect_level=skill.side_effect_level,
        metadata_quality=metadata_quality,
    )


def _domain_counts(rows: list[SkillInventoryRow]) -> list[SkillDomainSummary]:
    counts: dict[str, int] = {}
    for row in rows:
        for domain in row.domains:
            counts[domain] = counts.get(domain, 0) + 1
    return [
        SkillDomainSummary(name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
```

Call `_skills_inventory_summary(root)` from `build_project_dashboard_snapshot()` and pass it into `DashboardSnapshot`.

- [ ] **Step 4: Run collector tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/dashboard/models.py src/agentpack/dashboard/collectors.py tests/test_dashboard_collectors.py
git commit -m "feat: collect dashboard skills inventory"
```

## Task 4: Dashboard Skills Inventory Rendering

**Files:**
- Modify `src/agentpack/dashboard/renderers.py`
- Modify `tests/test_dashboard_renderer.py`

- [ ] **Step 1: Add renderer test**

Append to `tests/test_dashboard_renderer.py`:

```python
def test_render_dashboard_html_contains_skills_inventory_without_bodies() -> None:
    html = render_dashboard_html(
        DashboardSnapshot(
            project=ProjectInfo(name="repo", path="/tmp/repo"),
            skills_inventory=SkillsInventorySummary(
                available=True,
                total_skills=1,
                total_rules=0,
                domains=[SkillDomainSummary(name="testing", count=1)],
                sources=[
                    SkillInventorySourceSummary(
                        configured_path=".agentpack/skills",
                        resolved_path="/tmp/repo/.agentpack/skills",
                        exists=True,
                        file_count=1,
                    )
                ],
                rows=[
                    SkillInventoryRow(
                        name="pytest-debugging",
                        path=".agentpack/skills/pytest-debugging/SKILL.md",
                        source=".agentpack/skills",
                        domains=["testing"],
                        languages=["python"],
                        frameworks=["pytest"],
                        side_effect_level="command",
                        metadata_quality="explicit",
                    )
                ],
            ),
        )
    )

    assert "Skills Inventory" in html
    assert "pytest-debugging" in html
    assert "testing" in html
    assert ".agentpack/skills" in html
    assert "Use for pytest failures" not in html
```

- [ ] **Step 2: Render inventory section**

In `src/agentpack/dashboard/renderers.py`, add a `skills_inventory = _skills_inventory_panel(snapshot)` variable and insert it after the existing Skills section.

Add:

```python
def _skills_inventory_panel(snapshot: DashboardSnapshot) -> str:
    inventory = snapshot.skills_inventory
    if not inventory.available:
        reason = inventory.index_error or "No skills index available."
        return f"""
  <section>
    <h2>Skills Inventory</h2>
    <p>{_e(reason)}</p>
  </section>"""
    domains = "".join(
        f"<li>{_e(item.name)}: {item.count}</li>"
        for item in inventory.domains[:20]
    ) or "<li>No domains found.</li>"
    sources = "".join(
        "<tr>"
        f"<td><code>{_e(item.configured_path)}</code></td>"
        f"<td>{_e(item.resolved_path)}</td>"
        f"<td>{'yes' if item.exists else 'no'}</td>"
        f"<td>{item.file_count}</td>"
        "</tr>"
        for item in inventory.sources
    ) or '<tr><td colspan="4">No configured skill sources found.</td></tr>'
    rows = "".join(
        "<tr>"
        f"<td>{_e(item.name)}</td>"
        f"<td>{_e(', '.join(item.domains))}</td>"
        f"<td>{_e(item.source)}</td>"
        f"<td><code>{_e(item.path)}</code></td>"
        f"<td>{_e(item.side_effect_level)}</td>"
        f"<td>{_e(item.metadata_quality)}</td>"
        "</tr>"
        for item in inventory.rows
    ) or '<tr><td colspan="6">No skills discovered.</td></tr>'
    return f"""
  <section>
    <h2>Skills Inventory</h2>
    <div class="grid">
      <div class="metric"><strong>Skills</strong><span>{inventory.total_skills}</span></div>
      <div class="metric"><strong>Rules</strong><span>{inventory.total_rules}</span></div>
      <div class="metric"><strong>Uncategorized</strong><span>{inventory.uncategorized_count}</span></div>
      <div class="metric"><strong>Missing Metadata</strong><span>{inventory.missing_metadata_count}</span></div>
    </div>
    <p><small>Index: {_e(inventory.index_reason)}; refreshed: {'yes' if inventory.index_refreshed else 'no'}</small></p>
    <h3>Domains</h3>
    <ul>{domains}</ul>
    <h3>Directories</h3>
    <table><thead><tr><th>Configured</th><th>Resolved</th><th>Exists</th><th>Files</th></tr></thead><tbody>{sources}</tbody></table>
    <h3>Skills</h3>
    <table><thead><tr><th>Skill</th><th>Domain</th><th>Source</th><th>Path</th><th>Side Effect</th><th>Metadata</th></tr></thead><tbody>{rows}</tbody></table>
  </section>"""
```

- [ ] **Step 3: Run renderer tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_renderer.py tests/test_dashboard_command.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/agentpack/dashboard/renderers.py tests/test_dashboard_renderer.py
git commit -m "feat: render dashboard skills inventory"
```

## Task 5: Next Recommendation on Index Refresh Failure

**Files:**
- Modify `src/agentpack/commands/next_cmd.py`
- Modify `tests/test_next_command.py`

- [ ] **Step 1: Add failure recommendation test**

Append to `tests/test_next_command.py`:

```python
def test_next_recommends_skills_index_when_auto_refresh_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("[context]\n", encoding="utf-8")
    (tmp_path / ".agentpack" / "task.md").write_text("fix auth\n", encoding="utf-8")
    monkeypatch.setattr("agentpack.commands.next_cmd._context_is_fresh", lambda _root: (True, "fresh"))

    def fail_index(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("agentpack.commands.next_cmd.ensure_inventory_index", fail_index)

    result = CliRunner().invoke(app, ["next", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(item["kind"] == "skills_index_failed" for item in payload["recommendations"])
```

- [ ] **Step 2: Add recommendation helper**

In `src/agentpack/commands/next_cmd.py`, import `load_config` if not already imported and:

```python
from agentpack.router.skills_index import ensure_inventory_index
```

Add to `_recommendations(root)`:

```python
items.extend(_skills_index_recommendations(root))
```

Add:

```python
def _skills_index_recommendations(root) -> list[dict[str, str]]:
    cfg = load_config(root)
    try:
        ensure_inventory_index(root, cfg.skills.paths)
    except Exception as exc:
        return [
            {
                "kind": "skills_index_failed",
                "command": "agentpack skills index",
                "reason": f"automatic skills index refresh failed: {exc}",
            }
        ]
    return []
```

- [ ] **Step 3: Run next tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_next_command.py tests/test_workflow_automation.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/agentpack/commands/next_cmd.py tests/test_next_command.py
git commit -m "feat: recommend skills index repair"
```

## Task 6: Final Verification

- [ ] Run focused tests:

```bash
PYTHONPATH=src python -m pytest tests/test_router_discovery.py tests/test_route_command.py tests/test_router_scoring.py tests/test_dashboard_collectors.py tests/test_dashboard_renderer.py tests/test_dashboard_command.py tests/test_next_command.py tests/test_docs_links.py -q
```

- [ ] Run Ruff:

```bash
python -m ruff check src/agentpack/router/skills_index.py src/agentpack/router/discovery.py src/agentpack/commands/skills.py src/agentpack/commands/next_cmd.py src/agentpack/dashboard tests/test_router_discovery.py tests/test_route_command.py tests/test_dashboard_*.py tests/test_next_command.py
```

- [ ] Run full test suite:

```bash
PYTHONPATH=src python -m pytest -q
```

- [ ] Run smoke commands in a temp directory:

```bash
tmp=$(mktemp -d)
cd "$tmp"
PYTHONPATH=/Users/vishal/Documents/agentpack-release-0.3.15/src python -m agentpack.cli dashboard --json > dashboard.json
python -m json.tool dashboard.json >/dev/null
```

- [ ] Check generated dashboard has no remote/script references:

```bash
PYTHONPATH=/Users/vishal/Documents/agentpack-release-0.3.15/src python -m agentpack.cli dashboard
if rg -n 'https?://|<script' .agentpack/dashboard.html; then exit 1; fi
```

- [ ] Commit final fixes if any.

## Scope Boundaries

This plan does not add a new command, a daemon, or raw skill-body display. `agentpack watch` integration can be added later by calling `ensure_inventory_index()` when watched skill directories change; the MVP syncs lazily on the next dashboard, route, skills recommend, next, or MCP route call.
