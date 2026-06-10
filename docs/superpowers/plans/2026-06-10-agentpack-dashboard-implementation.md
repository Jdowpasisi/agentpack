# AgentPack Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `agentpack dashboard`, a local static dashboard that explains AgentPack context health, selected files, skill routing, feedback, learning, and benchmark quality from existing `.agentpack/` artifacts.

**Architecture:** Add a focused `agentpack.dashboard` package with Pydantic snapshot models, filesystem collectors, and a static HTML renderer. Add a Typer command that writes `.agentpack/dashboard.html`, supports `--json`, and optionally opens the generated file. Keep the first release read-only and static; global dashboard and local-server actions are separate later phases.

**Tech Stack:** Python 3.10+, Typer, Pydantic, pathlib, json/jsonl, stdlib `html`, pytest, existing AgentPack git/context/thread helpers.

---

## File Structure

- Create `src/agentpack/dashboard/__init__.py`
  - Package marker.
- Create `src/agentpack/dashboard/models.py`
  - Pydantic snapshot models used by collectors, renderer, and `--json`.
- Create `src/agentpack/dashboard/collectors.py`
  - Read project `.agentpack/` artifacts, cap JSONL rows, derive empty states, summarize feedback, and build `DashboardSnapshot`.
- Create `src/agentpack/dashboard/renderers.py`
  - Render static local HTML with inline CSS and no remote assets.
- Create `src/agentpack/dashboard/global_registry.py`
  - Phase 2 helper for global project registry; create later, not MVP-critical.
- Create `src/agentpack/commands/dashboard.py`
  - Typer CLI command for project dashboard.
- Modify `src/agentpack/cli.py`
  - Register dashboard command.
- Modify `docs/commands.md`
  - Document `agentpack dashboard`.
- Create `tests/test_dashboard_collectors.py`
  - Snapshot and missing-data behavior.
- Create `tests/test_dashboard_renderer.py`
  - HTML rendering and no remote assets.
- Create `tests/test_dashboard_command.py`
  - CLI output, `--json`, and `--open` behavior.
- Create `tests/test_dashboard_global.py`
  - Phase 2 global registry tests.

---

## Phase 1: Static Project Dashboard

### Task 1: Define Snapshot Models

**Files:**
- Create: `src/agentpack/dashboard/__init__.py`
- Create: `src/agentpack/dashboard/models.py`
- Test: `tests/test_dashboard_collectors.py`

- [ ] **Step 1: Write failing model test**

Create `tests/test_dashboard_collectors.py` with:

```python
from __future__ import annotations

from agentpack.dashboard.models import (
    DashboardSnapshot,
    ProjectInfo,
    TaskInfo,
    ContextHealth,
    SelectedFileRow,
    SkillRow,
    SkillSection,
)


def test_dashboard_snapshot_is_json_safe() -> None:
    snapshot = DashboardSnapshot(
        generated_at="2026-06-10T10:30:00Z",
        project=ProjectInfo(name="repo", path="/tmp/repo", branch="main", git_sha="abc123"),
        task=TaskInfo(text="fix auth", state="in_progress"),
        context=ContextHealth(status="fresh", mode="balanced", packed_tokens=1200, raw_tokens=40000),
        selected_files=[
            SelectedFileRow(
                path="src/auth.py",
                include_mode="full",
                score=120.0,
                tokens=450,
                reasons=["task keyword match"],
            )
        ],
        skills=SkillSection(
            task_specific=[
                SkillRow(
                    name="pytest-debugging",
                    path="skills/pytest-debugging/SKILL.md",
                    confidence=0.86,
                    score=93.0,
                    side_effect_level="command",
                    status="used_helpful",
                    reasons=["test task match"],
                )
            ]
        ),
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["schema_version"] == 1
    assert payload["project"]["name"] == "repo"
    assert payload["selected_files"][0]["path"] == "src/auth.py"
    assert payload["skills"]["task_specific"][0]["status"] == "used_helpful"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py::test_dashboard_snapshot_is_json_safe -q
```

Expected: import failure for `agentpack.dashboard`.

- [ ] **Step 3: Add model package**

Create `src/agentpack/dashboard/__init__.py`:

```python
"""Dashboard snapshot collection and rendering."""
```

Create `src/agentpack/dashboard/models.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ContextStatus = Literal["fresh", "stale", "missing", "unknown"]
TaskState = Literal["planned", "in_progress", "blocked", "done", "unknown"]
SkillFeedbackStatus = Literal[
    "none",
    "recommended_only",
    "used_helpful",
    "used_noisy",
    "ignored",
    "bad_recommendation",
]


class ProjectInfo(BaseModel):
    name: str
    path: str
    branch: str = ""
    git_sha: str = ""


class TaskInfo(BaseModel):
    text: str = ""
    state: TaskState = "unknown"
    thread_id: str | None = None


class ContextHealth(BaseModel):
    status: ContextStatus = "unknown"
    generated_at: str = ""
    mode: str = ""
    packed_tokens: int = 0
    raw_tokens: int = 0
    saving_pct: float = 0.0
    selected_files_count: int = 0
    stale_reason: str = ""


class SelectedFileRow(BaseModel):
    path: str
    include_mode: str = ""
    score: float = 0.0
    tokens: int = 0
    reasons: list[str] = Field(default_factory=list)


class SkillRow(BaseModel):
    name: str
    path: str = ""
    confidence: float = 0.0
    score: float = 0.0
    side_effect_level: str = ""
    status: SkillFeedbackStatus = "none"
    reasons: list[str] = Field(default_factory=list)


class SkillSection(BaseModel):
    task_specific: list[SkillRow] = Field(default_factory=list)
    baseline: list[SkillRow] = Field(default_factory=list)


class LearningArtifact(BaseModel):
    label: str
    path: str
    exists: bool
    excerpt: str = ""


class BenchmarkSummary(BaseModel):
    latest: dict[str, Any] = Field(default_factory=dict)
    averages: dict[str, float] = Field(default_factory=dict)
    misses: list[dict[str, Any]] = Field(default_factory=list)


class ThreadSummary(BaseModel):
    active_count: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    label: str
    command: str
    reason: str = ""


class DashboardSnapshot(BaseModel):
    schema_version: int = 1
    generated_at: str = ""
    project: ProjectInfo
    task: TaskInfo = Field(default_factory=TaskInfo)
    context: ContextHealth = Field(default_factory=ContextHealth)
    selected_files: list[SelectedFileRow] = Field(default_factory=list)
    skills: SkillSection = Field(default_factory=SkillSection)
    skill_feedback: dict[str, Any] = Field(default_factory=dict)
    learning: list[LearningArtifact] = Field(default_factory=list)
    benchmarks: BenchmarkSummary = Field(default_factory=BenchmarkSummary)
    threads: ThreadSummary = Field(default_factory=ThreadSummary)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
```

- [ ] **Step 4: Run passing test**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py::test_dashboard_snapshot_is_json_safe -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/dashboard/__init__.py src/agentpack/dashboard/models.py tests/test_dashboard_collectors.py
git commit -m "feat: add dashboard snapshot models"
```

---

### Task 2: Collect Project Dashboard Snapshot

**Files:**
- Create: `src/agentpack/dashboard/collectors.py`
- Modify: `tests/test_dashboard_collectors.py`

- [ ] **Step 1: Add collector tests for missing and populated projects**

Append to `tests/test_dashboard_collectors.py`:

```python
import json

from agentpack.dashboard.collectors import build_project_dashboard_snapshot


def test_project_dashboard_missing_agentpack_has_empty_states(tmp_path) -> None:
    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.project.name == tmp_path.name
    assert snapshot.context.status == "missing"
    assert any(action.command == "agentpack init --yes" for action in snapshot.suggested_actions)


def test_project_dashboard_reads_pack_metadata_and_metrics(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "task.md").write_text("fix auth token expiry\n", encoding="utf-8")
    (agentpack / "pack_metadata.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-10T10:30:00Z",
                "task": "fix auth token expiry",
                "mode": "balanced",
                "token_estimate": 1450,
                "raw_tokens": 40000,
                "saving_pct": 96.3,
                "selected_files_meta": [
                    {
                        "path": "src/auth/token.py",
                        "mode": "full",
                        "score": 120,
                        "tokens": 450,
                        "reasons": ["task keyword match", "related test"],
                    }
                ],
                "freshness": {"status": "fresh"},
            }
        ),
        encoding="utf-8",
    )
    (agentpack / "metrics.jsonl").write_text(
        json.dumps({"selection_recall": 0.8, "selection_token_precision": 0.5}) + "\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.task.text == "fix auth token expiry"
    assert snapshot.context.status == "fresh"
    assert snapshot.context.packed_tokens == 1450
    assert snapshot.context.raw_tokens == 40000
    assert snapshot.selected_files[0].path == "src/auth/token.py"
    assert snapshot.benchmarks.averages["selection_recall"] == 0.8
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q
```

Expected: fail because collector does not exist.

- [ ] **Step 3: Implement collector**

Create `src/agentpack/dashboard/collectors.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentpack.core import git
from agentpack.core.context_pack import load_pack_metadata
from agentpack.core.task_freshness import task_freshness
from agentpack.core.thread_context import list_thread_rows
from agentpack.dashboard.models import (
    BenchmarkSummary,
    ContextHealth,
    DashboardSnapshot,
    LearningArtifact,
    ProjectInfo,
    SelectedFileRow,
    SkillRow,
    SkillSection,
    SuggestedAction,
    TaskInfo,
    ThreadSummary,
)


MAX_JSONL_ROWS = 500


def build_project_dashboard_snapshot(root: Path) -> DashboardSnapshot:
    root = root.resolve()
    agentpack_dir = root / ".agentpack"
    meta = load_pack_metadata(root) if agentpack_dir.exists() else None
    task_text = _read_task(agentpack_dir / "task.md") or str((meta or {}).get("task") or "")
    freshness = task_freshness(root, meta) if meta else None
    context = _context_health(meta, freshness)
    selected_files = _selected_files(meta)
    feedback_rows = _load_jsonl(agentpack_dir / "skill_feedback.jsonl")
    skill_section = _skill_section(meta, feedback_rows)
    learning = _learning_artifacts(agentpack_dir)
    benchmarks = _benchmark_summary(
        _load_jsonl(agentpack_dir / "metrics.jsonl"),
        _load_jsonl(agentpack_dir / "benchmark_results.jsonl"),
    )
    threads = _thread_summary(root)
    actions = _suggested_actions(agentpack_dir, task_text, context, learning, benchmarks)

    return DashboardSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        project=_project_info(root),
        task=TaskInfo(text=task_text, state=_task_state(agentpack_dir / "task_state.md")),
        context=context,
        selected_files=selected_files,
        skills=skill_section,
        skill_feedback=_feedback_summary(feedback_rows),
        learning=learning,
        benchmarks=benchmarks,
        threads=threads,
        suggested_actions=actions,
    )


def _project_info(root: Path) -> ProjectInfo:
    sha = git.current_sha(root) if git.is_git_repo(root) else ""
    branch = git.current_branch(root) if git.is_git_repo(root) else ""
    return ProjectInfo(
        name=root.name,
        path=str(root),
        branch=branch or "",
        git_sha=(sha or "")[:12],
    )


def _read_task(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _task_state(path: Path) -> str:
    if not path.exists():
        return "unknown"
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.lower().startswith("status:"):
            value = line.split(":", 1)[1].strip()
            if value in {"planned", "in_progress", "blocked", "done"}:
                return value
    return "unknown"


def _context_health(meta: dict[str, Any] | None, freshness) -> ContextHealth:
    if not meta:
        return ContextHealth(status="missing")
    status = "fresh"
    stale_reason = ""
    if freshness is not None and getattr(freshness, "is_stale", False):
        status = "stale"
        stale_reason = getattr(freshness, "reason", "") or ""
    selected = meta.get("selected_files_meta") or []
    return ContextHealth(
        status=status,
        generated_at=str(meta.get("generated_at") or ""),
        mode=str(meta.get("mode") or ""),
        packed_tokens=int(meta.get("token_estimate") or meta.get("packed_tokens") or 0),
        raw_tokens=int(meta.get("raw_tokens") or 0),
        saving_pct=float(meta.get("saving_pct") or 0.0),
        selected_files_count=len(selected) if isinstance(selected, list) else 0,
        stale_reason=stale_reason,
    )


def _selected_files(meta: dict[str, Any] | None) -> list[SelectedFileRow]:
    rows: list[SelectedFileRow] = []
    for item in (meta or {}).get("selected_files_meta") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            SelectedFileRow(
                path=str(item.get("path") or ""),
                include_mode=str(item.get("mode") or item.get("include_mode") or ""),
                score=float(item.get("score") or 0.0),
                tokens=int(item.get("tokens") or item.get("estimated_tokens") or 0),
                reasons=[str(reason) for reason in (item.get("reasons") or [])[:5]],
            )
        )
    return rows


def _skill_section(meta: dict[str, Any] | None, feedback_rows: list[dict[str, Any]]) -> SkillSection:
    feedback = _feedback_summary_by_skill(feedback_rows)
    return SkillSection(
        task_specific=_skill_rows((meta or {}).get("selected_skills") or [], feedback),
        baseline=_skill_rows((meta or {}).get("baseline_skills") or [], feedback),
    )


def _skill_rows(values: list[Any], feedback: dict[str, str]) -> list[SkillRow]:
    rows: list[SkillRow] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill") if isinstance(item.get("skill"), dict) else item
        name = str(skill.get("name") or item.get("name") or "")
        rows.append(
            SkillRow(
                name=name,
                path=str(skill.get("path") or ""),
                confidence=float(item.get("confidence") or 0.0),
                score=float(item.get("score") or 0.0),
                side_effect_level=str(skill.get("side_effect_level") or ""),
                status=feedback.get(name.lower(), "none"),
                reasons=[str(reason) for reason in (item.get("reasons") or [])[:5]],
            )
        )
    return rows
```

Append the remaining helpers in the same file:

```python
def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-MAX_JSONL_ROWS:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _feedback_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"recent": rows[-20:], "summary_by_skill": _feedback_summary_by_skill(rows)}


def _feedback_summary_by_skill(rows: list[dict[str, Any]]) -> dict[str, str]:
    status: dict[str, str] = {}
    for row in rows:
        for skill in row.get("recommended_skills") or []:
            status[str(skill).lower()] = "recommended_only"
        for skill in row.get("used_skills") or []:
            feedback = str(row.get("user_feedback") or "").lower()
            status[str(skill).lower()] = "used_noisy" if feedback in {"bad", "noisy", "unhelpful"} else "used_helpful"
        for skill in row.get("ignored_skills") or []:
            status[str(skill).lower()] = "ignored"
        for skill in row.get("bad_recommendations") or []:
            status[str(skill).lower()] = "bad_recommendation"
    return status


def _learning_artifacts(agentpack_dir: Path) -> list[LearningArtifact]:
    artifacts = [
        ("Learning notes", "learning.md"),
        ("Daily summary", "daily-summary.md"),
        ("Agent lessons", "agent-lessons.md"),
        ("Skill progress", "skills-progress.json"),
        ("Learning feedback", "learning-feedback.jsonl"),
    ]
    return [
        LearningArtifact(
            label=label,
            path=f".agentpack/{name}",
            exists=(agentpack_dir / name).exists(),
            excerpt=_bounded_excerpt(agentpack_dir / name),
        )
        for label, name in artifacts
    ]


def _bounded_excerpt(path: Path, limit: int = 1200) -> str:
    if not path.exists() or path.suffix == ".jsonl":
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def _benchmark_summary(metrics_rows: list[dict[str, Any]], benchmark_rows: list[dict[str, Any]]) -> BenchmarkSummary:
    numeric_keys = [
        "selection_recall",
        "selection_precision",
        "selection_token_precision",
        "skill_recall_at_3",
        "skill_precision_at_3",
        "skill_mrr",
        "skill_noise_rate",
    ]
    recent = metrics_rows[-10:] + benchmark_rows[-10:]
    averages: dict[str, float] = {}
    for key in numeric_keys:
        values = [float(row[key]) for row in recent if isinstance(row.get(key), int | float)]
        if values:
            averages[key] = sum(values) / len(values)
    latest = (benchmark_rows or metrics_rows or [{}])[-1]
    misses = [miss for row in benchmark_rows[-5:] for miss in (row.get("misses") or []) if isinstance(miss, dict)]
    return BenchmarkSummary(latest=latest, averages=averages, misses=misses[:20])


def _thread_summary(root: Path) -> ThreadSummary:
    rows = list_thread_rows(root, active_only=True)
    return ThreadSummary(active_count=len(rows), conflicts=[])


def _suggested_actions(
    agentpack_dir: Path,
    task_text: str,
    context: ContextHealth,
    learning: list[LearningArtifact],
    benchmarks: BenchmarkSummary,
) -> list[SuggestedAction]:
    actions: list[SuggestedAction] = []
    if not agentpack_dir.exists():
        actions.append(SuggestedAction(label="Initialize AgentPack", command="agentpack init --yes", reason="No .agentpack directory exists."))
    if not task_text:
        actions.append(SuggestedAction(label="Start a task", command='agentpack work "describe the task"', reason="No current task found."))
    if context.status in {"missing", "stale"}:
        actions.append(SuggestedAction(label="Refresh context", command="agentpack pack --task auto", reason=f"Context is {context.status}."))
    if not any(item.exists for item in learning):
        actions.append(SuggestedAction(label="Generate learning notes", command="agentpack learn", reason="No learning artifacts found."))
    if not benchmarks.averages:
        actions.append(SuggestedAction(label="Initialize benchmarks", command="agentpack benchmark --init", reason="No benchmark metrics found."))
    return actions
```

- [ ] **Step 4: Run collector tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/dashboard/collectors.py tests/test_dashboard_collectors.py
git commit -m "feat: collect dashboard snapshot"
```

---

### Task 3: Render Static Local HTML

**Files:**
- Create: `src/agentpack/dashboard/renderers.py`
- Test: `tests/test_dashboard_renderer.py`

- [ ] **Step 1: Write renderer tests**

Create `tests/test_dashboard_renderer.py`:

```python
from __future__ import annotations

from agentpack.dashboard.models import (
    ContextHealth,
    DashboardSnapshot,
    ProjectInfo,
    SelectedFileRow,
    SuggestedAction,
    TaskInfo,
)
from agentpack.dashboard.renderers import render_dashboard_html


def test_render_dashboard_html_contains_core_sections() -> None:
    html = render_dashboard_html(
        DashboardSnapshot(
            generated_at="2026-06-10T10:30:00Z",
            project=ProjectInfo(name="repo", path="/tmp/repo", branch="main", git_sha="abc123"),
            task=TaskInfo(text="fix auth", state="in_progress"),
            context=ContextHealth(status="fresh", mode="balanced", packed_tokens=1200, raw_tokens=40000),
            selected_files=[SelectedFileRow(path="src/auth.py", include_mode="full", score=120)],
            suggested_actions=[SuggestedAction(label="Refresh context", command="agentpack pack --task auto")],
        )
    )

    assert "AgentPack Dashboard" in html
    assert "fix auth" in html
    assert "src/auth.py" in html
    assert "agentpack pack --task auto" in html


def test_render_dashboard_html_uses_no_remote_assets() -> None:
    html = render_dashboard_html(
        DashboardSnapshot(project=ProjectInfo(name="repo", path="/tmp/repo"))
    )

    assert "https://" not in html
    assert "http://" not in html
    assert "<script" not in html.lower()
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_renderer.py -q
```

Expected: fail because renderer does not exist.

- [ ] **Step 3: Implement renderer**

Create `src/agentpack/dashboard/renderers.py`:

```python
from __future__ import annotations

import html

from agentpack.dashboard.models import DashboardSnapshot


def render_dashboard_html(snapshot: DashboardSnapshot) -> str:
    files = "".join(
        "<tr>"
        f"<td><code>{_e(item.path)}</code></td>"
        f"<td>{_e(item.include_mode)}</td>"
        f"<td>{item.score:.1f}</td>"
        f"<td>{item.tokens}</td>"
        f"<td>{_e(', '.join(item.reasons[:3]))}</td>"
        "</tr>"
        for item in snapshot.selected_files[:50]
    ) or '<tr><td colspan="5">No selected files found.</td></tr>'

    skills = _skill_rows(snapshot.skills.task_specific, "task-specific") + _skill_rows(snapshot.skills.baseline, "baseline")
    if not skills:
        skills = '<tr><td colspan="6">No skill recommendations found.</td></tr>'

    learning = "".join(
        "<li>"
        f"{_e(item.label)}: <code>{_e(item.path)}</code> "
        f"{'present' if item.exists else 'missing'}"
        "</li>"
        for item in snapshot.learning
    ) or "<li>No learning artifacts checked.</li>"

    actions = "".join(
        f"<li><strong>{_e(item.label)}</strong><br><code>{_e(item.command)}</code><br><small>{_e(item.reason)}</small></li>"
        for item in snapshot.suggested_actions
    ) or "<li>No suggested actions.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentPack Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #1f2328; background: #f6f8fa; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ padding: 24px 0; border-bottom: 1px solid #d0d7de; }}
    section {{ margin: 24px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .metric {{ background: white; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d0d7de; }}
    th, td {{ border-bottom: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }}
    code {{ background: #eef1f4; padding: 1px 4px; border-radius: 4px; }}
    small {{ color: #57606a; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>AgentPack Dashboard</h1>
    <p><strong>Project:</strong> {_e(snapshot.project.name)} <small>{_e(snapshot.project.path)}</small></p>
    <p><strong>Task:</strong> {_e(snapshot.task.text or "No task found")}</p>
    <p><strong>Generated:</strong> {_e(snapshot.generated_at)}</p>
  </header>
  <section>
    <h2>Context Health</h2>
    <div class="grid">
      <div class="metric"><strong>Status</strong><br>{_e(snapshot.context.status)}</div>
      <div class="metric"><strong>Mode</strong><br>{_e(snapshot.context.mode or "unknown")}</div>
      <div class="metric"><strong>Packed Tokens</strong><br>{snapshot.context.packed_tokens:,}</div>
      <div class="metric"><strong>Raw Tokens</strong><br>{snapshot.context.raw_tokens:,}</div>
      <div class="metric"><strong>Selected Files</strong><br>{snapshot.context.selected_files_count}</div>
    </div>
  </section>
  <section>
    <h2>Selected Files</h2>
    <table><thead><tr><th>Path</th><th>Mode</th><th>Score</th><th>Tokens</th><th>Reasons</th></tr></thead><tbody>{files}</tbody></table>
  </section>
  <section>
    <h2>Skills</h2>
    <table><thead><tr><th>Name</th><th>Type</th><th>Confidence</th><th>Score</th><th>Status</th><th>Reasons</th></tr></thead><tbody>{skills}</tbody></table>
  </section>
  <section>
    <h2>Learning</h2>
    <ul>{learning}</ul>
  </section>
  <section>
    <h2>Suggested Actions</h2>
    <ul>{actions}</ul>
  </section>
</main>
</body>
</html>
"""


def _skill_rows(items, kind: str) -> str:
    return "".join(
        "<tr>"
        f"<td>{_e(item.name)}</td>"
        f"<td>{kind}</td>"
        f"<td>{item.confidence:.2f}</td>"
        f"<td>{item.score:.1f}</td>"
        f"<td>{_e(item.status)}</td>"
        f"<td>{_e(', '.join(item.reasons[:3]))}</td>"
        "</tr>"
        for item in items
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
```

- [ ] **Step 4: Run renderer tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_renderer.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/dashboard/renderers.py tests/test_dashboard_renderer.py
git commit -m "feat: render dashboard html"
```

---

### Task 4: Add `agentpack dashboard` CLI

**Files:**
- Create: `src/agentpack/commands/dashboard.py`
- Modify: `src/agentpack/cli.py`
- Test: `tests/test_dashboard_command.py`

- [ ] **Step 1: Write CLI tests**

Create `tests/test_dashboard_command.py`:

```python
from __future__ import annotations

import json

from typer.testing import CliRunner

from agentpack.cli import app


runner = CliRunner()


def test_dashboard_writes_project_html(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("fix auth\n", encoding="utf-8")

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / ".agentpack" / "dashboard.html").read_text(encoding="utf-8")
    assert "AgentPack Dashboard" in html
    assert "fix auth" in html


def test_dashboard_json_outputs_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    result = runner.invoke(app, ["dashboard", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["project"]["path"] == str(tmp_path)
```

- [ ] **Step 2: Run failing CLI tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_command.py -q
```

Expected: fail because command is not registered.

- [ ] **Step 3: Implement command**

Create `src/agentpack/commands/dashboard.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from agentpack.commands._shared import _atomic_write, _root, console
from agentpack.dashboard.collectors import build_project_dashboard_snapshot
from agentpack.dashboard.renderers import render_dashboard_html


def register(app: typer.Typer) -> None:
    @app.command()
    def dashboard(
        json_output: bool = typer.Option(False, "--json", help="Print normalized dashboard snapshot JSON."),
        open_browser: bool = typer.Option(False, "--open", help="Open the generated HTML dashboard."),
        output: str = typer.Option("", "--output", "-o", help="Dashboard HTML output path."),
    ) -> None:
        """Generate a local AgentPack dashboard."""
        root = _root()
        snapshot = build_project_dashboard_snapshot(root)
        if json_output:
            typer.echo(json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True))
            return

        out = root / (output or ".agentpack/dashboard.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out, render_dashboard_html(snapshot))
        console.print(f"[green]✓[/] Wrote [bold]{out}[/]")
        if open_browser:
            _open_file(out)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["cmd", "/c", "start", "", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
```

Modify `src/agentpack/cli.py` imports:

```python
    dashboard,
```

Add it to the registration list near `stats`:

```python
    dashboard,
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_command.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/commands/dashboard.py src/agentpack/cli.py tests/test_dashboard_command.py
git commit -m "feat: add dashboard command"
```

---

### Task 5: Improve Snapshot Coverage for Skills, Benchmarks, and Learning

**Files:**
- Modify: `src/agentpack/dashboard/collectors.py`
- Modify: `tests/test_dashboard_collectors.py`

- [ ] **Step 1: Add regression tests for skill feedback and benchmarks**

Append to `tests/test_dashboard_collectors.py`:

```python
def test_project_dashboard_summarizes_skill_feedback(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "skill_feedback.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"recommended_skills": ["auth-review"], "task": "fix auth"}),
                json.dumps({"used_skills": ["auth-review"], "tests_passed": True, "user_feedback": "helpful"}),
                json.dumps({"ignored_skills": ["deploy-checklist"], "user_feedback": "ignored"}),
                json.dumps({"bad_recommendations": ["deploy-checklist"], "user_feedback": "noisy"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (agentpack / "pack_metadata.json").write_text(
        json.dumps(
            {
                "selected_skills": [
                    {
                        "skill": {"name": "auth-review", "path": "skills/auth-review/SKILL.md", "side_effect_level": "none"},
                        "confidence": 0.8,
                        "score": 80,
                        "reasons": ["task keyword match"],
                    },
                    {
                        "skill": {"name": "deploy-checklist", "path": "skills/deploy/SKILL.md", "side_effect_level": "external"},
                        "confidence": 0.7,
                        "score": 70,
                        "reasons": ["task keyword match"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    statuses = {skill.name: skill.status for skill in snapshot.skills.task_specific}
    assert statuses["auth-review"] == "used_helpful"
    assert statuses["deploy-checklist"] == "bad_recommendation"


def test_project_dashboard_caps_jsonl_rows(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "metrics.jsonl").write_text(
        "".join(json.dumps({"selection_recall": idx / 1000}) + "\n" for idx in range(700)),
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert 0.0 < snapshot.benchmarks.averages["selection_recall"] <= 1.0
```

- [ ] **Step 2: Run tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q
```

Expected: fail until skill feedback status precedence and capped JSONL aggregation are implemented.

- [ ] **Step 3: Implement feedback status precedence and capped JSONL reads**

Update `_feedback_summary_by_skill` in `src/agentpack/dashboard/collectors.py` so later explicit states win:

```python
precedence = {
    "none": 0,
    "recommended_only": 1,
    "ignored": 2,
    "used_helpful": 3,
    "used_noisy": 4,
    "bad_recommendation": 5,
}
```

Assign a new status only when `precedence[new_status] >= precedence[current_status]`.

Ensure every JSONL helper reads at most the newest 500 valid rows, skipping malformed JSON lines and missing files without raising.

- [ ] **Step 4: Run collector tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/dashboard/collectors.py tests/test_dashboard_collectors.py
git commit -m "feat: summarize dashboard quality signals"
```

---

### Task 6: Documentation and Release Checks

**Files:**
- Modify: `docs/commands.md`
- Modify: `README.md`
- Test: existing docs and command tests

- [ ] **Step 1: Document command**

Add to the command table in `docs/commands.md`:

```markdown
| `agentpack dashboard` | Generate a local HTML dashboard for context, skills, learning, and quality |
```

Add a section near `agentpack stats`:

Add this Markdown:

````markdown
### `agentpack dashboard`

Generate a static local dashboard from existing `.agentpack/` artifacts.

```bash
agentpack dashboard
agentpack dashboard --open
agentpack dashboard --json
```

The dashboard writes `.agentpack/dashboard.html` by default. It is local-only,
uses inline CSS, and does not load remote scripts or assets. Missing artifacts
render empty states with suggested commands such as `agentpack pack --task auto`,
`agentpack learn`, and `agentpack benchmark --init`.
````

- [ ] **Step 2: Add README mention**

Add a compact bullet under the command overview in `README.md`:

```markdown
| `agentpack dashboard` | Local HTML control plane for context, skills, learning, and benchmark quality |
```

- [ ] **Step 3: Run relevant tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py tests/test_dashboard_renderer.py tests/test_dashboard_command.py tests/test_docs_links.py -q
```

Expected: pass.

- [ ] **Step 4: Run full suite**

Run:

```bash
PYTHONPATH=src python -m pytest -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/commands.md
git commit -m "docs: document dashboard command"
```

---

## Follow-up Plan Boundaries

This document is the executable plan for Phase 1 only: a static project dashboard. The PRD intentionally includes later global and interactive capabilities, but those should be split into separate implementation plans after Phase 1 lands.

### Phase 2: Static Global Dashboard

Write a separate plan for:

- `src/agentpack/dashboard/global_registry.py`
- `agentpack dashboard --global`
- `~/.agentpack/projects.json`
- global skill feedback aggregation
- global lesson candidate inbox
- tests in `tests/test_dashboard_global.py`

Acceptance criteria for that future plan:

- registry updates are explicit and deterministic
- duplicate project paths are upserted, not duplicated
- `--global` can render with zero registered projects
- global dashboard does not read raw repo files from other projects

### Phase 3: Local Server Actions

Write a separate plan for:

- `src/agentpack/dashboard/server.py`
- `agentpack dashboard --serve`
- `GET /`
- `GET /api/snapshot`
- later `POST` actions for feedback and lesson promotion

Acceptance criteria for that future plan:

- server binds to `127.0.0.1` only
- no write action exists without an explicit POST endpoint and tests
- direct actions reuse CLI/domain helpers rather than duplicating logic

### Phase 4: Team Export

Write a separate plan for:

- redacted team dashboard export
- CI artifact mode
- opt-in team lessons
- privacy and redaction tests

Acceptance criteria for that future plan:

- exported dashboard contains no personal skill history by default
- no source snippets are exported unless bounded and redacted
- CI artifact generation is opt-in

---

## Verification Checklist

- [ ] `PYTHONPATH=src python -m pytest tests/test_dashboard_collectors.py -q`
- [ ] `PYTHONPATH=src python -m pytest tests/test_dashboard_renderer.py -q`
- [ ] `PYTHONPATH=src python -m pytest tests/test_dashboard_command.py -q`
- [ ] `PYTHONPATH=src python -m pytest -q`
- [ ] `python -m ruff check src/agentpack/dashboard src/agentpack/commands/dashboard.py tests/test_dashboard_*.py`
- [ ] `PYTHONPATH=src python -m agentpack.cli dashboard`
- [ ] `PYTHONPATH=src python -m agentpack.cli dashboard --json`
- [ ] inspect `.agentpack/dashboard.html` and verify no `http://`, `https://`, or `<script` references

---

## Spec Coverage Review

- Project overview: Tasks 1, 2, 3, 4.
- Context health: Tasks 1, 2, 3.
- Selected files: Tasks 1, 2, 3.
- Skill routing and feedback visibility: Tasks 2, 5.
- Learning artifacts: Tasks 2, 3.
- Benchmarks: Tasks 2, 5.
- Suggested actions: Tasks 2, 3.
- JSON output: Task 4.
- Static HTML: Task 3.
- Global dashboard: follow-up Phase 2 plan boundary.
- Local server: follow-up Phase 3 plan boundary.
- Privacy and no remote assets: Task 3 tests plus verification checklist.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-10-agentpack-dashboard-implementation.md`.

Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.
