# AgentPack Learn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `agentpack learn`, a local-first learning layer for AI-assisted development that turns AgentPack task context and git changes into developer learning notes, a durable skill map, and compact lessons that future coding agents can use.

**Architecture:** Add a focused learning domain module that builds a structured report from task text, git changes, selected pack files, offline summaries, and redacted diffs. Split output into two first-class products: a human learning artifact (`learning.md`, `daily-summary.md`, `skills-progress.json`) and an agent learning artifact (`agent-lessons.md`) that can be injected into future context packs. Keep CLI parsing in a new Typer command module, keep report rendering in a separate renderer, and reuse AgentPack's existing task/thread, pack, git, ignore, scanner, and redaction primitives. MVP is deterministic and offline; provider-backed LLM summaries remain out of scope.

**Tech Stack:** Python 3.10+, Typer, Pydantic, Rich, pathlib, subprocess/git, pytest.

---

## File Structure

- Create `src/agentpack/learning/__init__.py`
  - Package marker and exports for learning report types.
- Create `src/agentpack/learning/models.py`
  - Pydantic models for `LearningReport`, `LearningCard`, `QuizQuestion`, `LearningSourceFile`, `AgentLesson`, `SkillEvidence`, `SkillProgress`, and `LearningOptions`.
- Create `src/agentpack/learning/collector.py`
  - Collect task, git diff metadata, pack selected files, changed paths, and redacted snippets.
- Create `src/agentpack/learning/extractor.py`
  - Deterministically infer concepts, decisions, risks, tests touched, practice prompts, agent lessons, and skill evidence.
- Create `src/agentpack/learning/renderers.py`
  - Render `LearningReport` to Markdown, agent-lesson Markdown, and JSON-safe dicts.
- Create `src/agentpack/learning/skill_map.py`
  - Update `.agentpack/skills-progress.json` from task-level skill evidence.
- Create `src/agentpack/learning/quality.py`
  - Score whether output is task-specific enough to beat generic journal/PR-summary competitors.
- Create `src/agentpack/commands/learn.py`
  - Typer command and output writing.
- Modify `src/agentpack/cli.py`
  - Register `learn`.
- Modify `src/agentpack/renderers/markdown.py`
  - Include bounded `.agentpack/agent-lessons.md` section in future context packs when enabled.
- Modify `src/agentpack/core/git.py`
  - Add small helpers for diff stats and recent commits when needed by learning collector.
- Modify `src/agentpack/core/config.py`
  - Add `[learning]` defaults for output paths, limits, skill map, agent lessons, and quality gate.
- Modify `src/agentpack/commands/init.py`
  - Ensure generated `.agentpack/.gitignore` ignores learning output by default.
- Modify `docs/commands.md`, `docs/configuration.md`, `README.md`
  - Document command, defaults, and privacy posture.
- Create `tests/test_learning_models.py`
- Create `tests/test_learning_extractor.py`
- Create `tests/test_learning_renderer.py`
- Create `tests/test_learning_skill_map.py`
- Create `tests/test_learning_quality.py`
- Create `tests/test_learn_command.py`
- Update `tests/test_init.py`

---

## Competitive Edge Requirements

AgentPack Learn must not become another daily journal or PR summarizer. The MVP must ship these differentiators:

- Human learning: explain concepts, decisions, tests, risks, quiz questions, and next practice in developer language.
- Agent learning: write compact repo-specific rules for future AI agents, such as "When editing Typer commands, update command docs and CLI tests."
- Skill graph: persist concept growth over time with evidence paths and task names, not vanity productivity metrics.
- Groundedness: every learning card and agent lesson must cite at least one changed file when possible.
- Quality gate: report when output is too generic, missing evidence, or only restates commit activity.
- Privacy posture: local-first, bounded diffs, redaction reused, generated artifacts ignored by default.

## Competitor Positioning

- Versus `rwd`: AgentPack Learn is not only a daily journal; it converts work into reusable developer skill evidence and future-agent instructions.
- Versus Worktale/Git recap tools: AgentPack Learn does not measure productivity or create public proof; it teaches from exact task context and changed files.
- Versus PR-Agent/Presubmit: AgentPack Learn is not a reviewer; it runs after or during task work to explain what developer and next agent should learn.
- Versus codebase wiki tools: AgentPack Learn is task-scoped and incremental; it avoids broad documentation generation unless a changed file proves relevance.

---

### Task 1: Add Learning Config

**Files:**
- Modify: `src/agentpack/core/config.py`
- Test: `tests/test_learning_models.py`

- [ ] **Step 1: Write config defaults test**

Add this test file:

```python
from agentpack.core.config import DEFAULT_CONFIG, Config


def test_learning_config_defaults():
    cfg = DEFAULT_CONFIG

    assert cfg.learning.markdown_output == ".agentpack/learning.md"
    assert cfg.learning.daily_output == ".agentpack/daily-summary.md"
    assert cfg.learning.max_changed_files == 20
    assert cfg.learning.max_diff_chars_per_file == 1200
    assert cfg.learning.max_cards == 5
    assert cfg.learning.max_quiz_questions == 5
    assert cfg.learning.skill_map_output == ".agentpack/skills-progress.json"
    assert cfg.learning.agent_lessons_output == ".agentpack/agent-lessons.md"
    assert cfg.learning.inject_agent_lessons is True
    assert cfg.learning.min_groundedness_score == 70


def test_learning_config_model_accepts_overrides():
    cfg = Config.model_validate({
        "learning": {
            "markdown_output": ".agentpack/custom-learning.md",
            "daily_output": ".agentpack/custom-daily.md",
            "max_changed_files": 7,
            "max_diff_chars_per_file": 400,
            "max_cards": 3,
            "max_quiz_questions": 2,
            "skill_map_output": ".agentpack/custom-skills.json",
            "agent_lessons_output": ".agentpack/custom-agent-lessons.md",
            "inject_agent_lessons": False,
            "min_groundedness_score": 80,
        }
    })

    assert cfg.learning.markdown_output == ".agentpack/custom-learning.md"
    assert cfg.learning.daily_output == ".agentpack/custom-daily.md"
    assert cfg.learning.max_changed_files == 7
    assert cfg.learning.max_diff_chars_per_file == 400
    assert cfg.learning.max_cards == 3
    assert cfg.learning.max_quiz_questions == 2
    assert cfg.learning.skill_map_output == ".agentpack/custom-skills.json"
    assert cfg.learning.agent_lessons_output == ".agentpack/custom-agent-lessons.md"
    assert cfg.learning.inject_agent_lessons is False
    assert cfg.learning.min_groundedness_score == 80
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_learning_models.py -v
```

Expected: fail because `Config` has no `learning` field.

- [ ] **Step 3: Add config model**

Modify `src/agentpack/core/config.py`:

```python
class LearningConfig(BaseModel):
    markdown_output: str = ".agentpack/learning.md"
    daily_output: str = ".agentpack/daily-summary.md"
    skill_map_output: str = ".agentpack/skills-progress.json"
    agent_lessons_output: str = ".agentpack/agent-lessons.md"
    inject_agent_lessons: bool = True
    max_changed_files: int = 20
    max_diff_chars_per_file: int = 1200
    max_cards: int = 5
    max_quiz_questions: int = 5
    min_groundedness_score: int = 70
```

Add field to `Config`:

```python
learning: LearningConfig = Field(default_factory=LearningConfig)
```

Add section to `CONFIG_TEMPLATE`:

```toml
[learning]
markdown_output = ".agentpack/learning.md"
daily_output = ".agentpack/daily-summary.md"
skill_map_output = ".agentpack/skills-progress.json"
agent_lessons_output = ".agentpack/agent-lessons.md"
inject_agent_lessons = true
max_changed_files = 20
max_diff_chars_per_file = 1200
max_cards = 5
max_quiz_questions = 5
min_groundedness_score = 70
```

- [ ] **Step 4: Run passing test**

Run:

```bash
pytest tests/test_learning_models.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/core/config.py tests/test_learning_models.py
git commit -m "feat: add learning config defaults"
```

---

### Task 2: Define Learning Report Models

**Files:**
- Create: `src/agentpack/learning/__init__.py`
- Create: `src/agentpack/learning/models.py`
- Test: `tests/test_learning_models.py`

- [ ] **Step 1: Add model validation tests**

Append to `tests/test_learning_models.py`:

```python
from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningOptions,
    LearningReport,
    LearningSourceFile,
    QuizQuestion,
    SkillEvidence,
    SkillProgress,
)


def test_learning_report_serializes_to_json_safe_dict():
    report = LearningReport(
        task="Add auth retry handling",
        scope="task",
        since="HEAD~1",
        source_files=[
            LearningSourceFile(
                path="src/app/auth.py",
                change_kind="modified",
                why="Changed token refresh behavior",
                concepts=["auth", "retry"],
            )
        ],
        summary=["Added retry handling for expired auth tokens."],
        concepts=["authentication", "retry logic"],
        decisions=["Keep retry local to auth client."],
        risks=["Retry loops can hide permanent auth failures."],
        tests=["Covered expired token retry."],
        learning_cards=[
            LearningCard(
                title="Retry Boundaries",
                body="Retries need a clear max attempt count and failure path.",
                files=["src/app/auth.py"],
            )
        ],
        quiz=[
            QuizQuestion(
                question="Why should auth retries have a max attempt count?",
                answer="To avoid infinite loops and surface permanent failures.",
            )
        ],
        agent_lessons=[
            AgentLesson(
                rule="When changing auth retry behavior, verify max attempts and final failure path.",
                evidence_files=["src/app/auth.py"],
                reason="Retry changes can otherwise hide permanent authentication failures.",
            )
        ],
        skill_evidence=[
            SkillEvidence(
                skill="retry logic",
                task="Add auth retry handling",
                evidence_files=["src/app/auth.py"],
                confidence=80,
            )
        ],
        next_practice="Add one regression test for max retry attempts.",
    )

    payload = report.model_dump(mode="json")

    assert payload["task"] == "Add auth retry handling"
    assert payload["source_files"][0]["path"] == "src/app/auth.py"
    assert payload["learning_cards"][0]["title"] == "Retry Boundaries"
    assert payload["agent_lessons"][0]["rule"].startswith("When changing auth retry")
    assert payload["skill_evidence"][0]["skill"] == "retry logic"


def test_learning_options_defaults():
    options = LearningOptions()

    assert options.scope == "task"
    assert options.since is None
    assert options.today is False
    assert options.json_output is False


def test_skill_progress_tracks_evidence_without_productivity_metrics():
    progress = SkillProgress(
        skill="CLI design",
        task_count=2,
        last_task="Add AgentPack Learn",
        evidence=[
            SkillEvidence(
                skill="CLI design",
                task="Add AgentPack Learn",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=75,
            )
        ],
    )

    payload = progress.model_dump(mode="json")

    assert payload["skill"] == "CLI design"
    assert "commits_per_day" not in payload
    assert payload["evidence"][0]["evidence_files"] == ["src/agentpack/commands/learn.py"]
```

- [ ] **Step 2: Run failing model tests**

Run:

```bash
pytest tests/test_learning_models.py -v
```

Expected: fail because `agentpack.learning` package does not exist.

- [ ] **Step 3: Create models**

Create `src/agentpack/learning/__init__.py`:

```python
from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningOptions,
    LearningReport,
    LearningSourceFile,
    QuizQuestion,
    SkillEvidence,
    SkillProgress,
)

__all__ = [
    "AgentLesson",
    "LearningCard",
    "LearningOptions",
    "LearningReport",
    "LearningSourceFile",
    "QuizQuestion",
    "SkillEvidence",
    "SkillProgress",
]
```

Create `src/agentpack/learning/models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class LearningOptions(BaseModel):
    scope: str = "task"
    since: str | None = None
    today: bool = False
    json_output: bool = False


class LearningSourceFile(BaseModel):
    path: str
    change_kind: str
    why: str
    concepts: list[str] = Field(default_factory=list)


class LearningCard(BaseModel):
    title: str
    body: str
    files: list[str] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    question: str
    answer: str


class AgentLesson(BaseModel):
    rule: str
    evidence_files: list[str] = Field(default_factory=list)
    reason: str = ""


class SkillEvidence(BaseModel):
    skill: str
    task: str
    evidence_files: list[str] = Field(default_factory=list)
    confidence: int = 0


class SkillProgress(BaseModel):
    skill: str
    task_count: int = 0
    last_task: str = ""
    evidence: list[SkillEvidence] = Field(default_factory=list)


class LearningReport(BaseModel):
    task: str
    scope: str
    since: str | None = None
    source_files: list[LearningSourceFile] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    learning_cards: list[LearningCard] = Field(default_factory=list)
    quiz: list[QuizQuestion] = Field(default_factory=list)
    agent_lessons: list[AgentLesson] = Field(default_factory=list)
    skill_evidence: list[SkillEvidence] = Field(default_factory=list)
    next_practice: str = ""
```

- [ ] **Step 4: Run passing model tests**

Run:

```bash
pytest tests/test_learning_models.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/learning tests/test_learning_models.py
git commit -m "feat: add learning report models"
```

---

### Task 3: Add Git Diff Helpers

**Files:**
- Modify: `src/agentpack/core/git.py`
- Test: `tests/test_git.py`

- [ ] **Step 1: Add tests for changed file stats and diffs**

Append to `tests/test_git.py`:

```python
from pathlib import Path
import subprocess

from agentpack.core import git


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_diff_name_status_includes_modified_and_added(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "app.py").write_text("print('one')\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "app.py").write_text("print('two')\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("print('new')\n", encoding="utf-8")

    status = git.diff_name_status(tmp_path)

    assert status["app.py"] == "modified"
    assert status["new.py"] == "untracked"


def test_file_diff_redacts_and_truncates(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "config.py").write_text("TOKEN = 'old'\n", encoding="utf-8")
    _git(tmp_path, "add", "config.py")
    _git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "config.py").write_text(
        "TOKEN = 'sk-1234567890123456789012345678901234567890'\n",
        encoding="utf-8",
    )

    diff, warnings = git.file_diff(tmp_path, "config.py", max_chars=200)

    assert "[REDACTED:openai-key]" in diff
    assert "sk-1234567890" not in diff
    assert warnings
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_git.py::test_diff_name_status_includes_modified_and_added tests/test_git.py::test_file_diff_redacts_and_truncates -v
```

Expected: fail because helpers do not exist.

- [ ] **Step 3: Implement git helpers**

Add to `src/agentpack/core/git.py`:

```python
def diff_name_status(root: Path, since: str | None = None) -> dict[str, str]:
    """Return changed path -> change kind for learning/reporting commands."""
    result: dict[str, str] = {}
    args = ["git", "diff", "--name-status"]
    if since:
        args.extend([since, "HEAD"])
    out = _run(args, root)
    if out:
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                status, path = parts[0], parts[-1]
                result[path] = _status_label(status)

    status_out = _run(["git", "status", "--short"], root)
    if status_out:
        for line in status_out.splitlines():
            if line.startswith("?? "):
                result[line[3:].strip()] = "untracked"
    return result


def file_diff(root: Path, path: str, *, since: str | None = None, max_chars: int = 1200) -> tuple[str, list[str]]:
    """Return a redacted, bounded diff for one file."""
    from agentpack.core.redactor import redact_secrets

    args = ["git", "diff", "--", path]
    if since:
        args = ["git", "diff", since, "HEAD", "--", path]
    out = _run(args, root) or ""
    if not out and (root / path).exists():
        out = (root / path).read_text(encoding="utf-8", errors="replace")
    redacted, warnings = redact_secrets(out[:max_chars], path)
    if len(out) > max_chars:
        redacted += "\n[diff truncated]\n"
    return redacted, warnings


def _status_label(status: str) -> str:
    code = status[:1]
    if code == "A":
        return "added"
    if code == "D":
        return "deleted"
    if code == "R":
        return "renamed"
    if code == "C":
        return "copied"
    return "modified"
```

- [ ] **Step 4: Run passing tests**

Run:

```bash
pytest tests/test_git.py::test_diff_name_status_includes_modified_and_added tests/test_git.py::test_file_diff_redacts_and_truncates -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/core/git.py tests/test_git.py
git commit -m "feat: expose bounded git diffs for learning reports"
```

---

### Task 4: Build Learning Collector

**Files:**
- Create: `src/agentpack/learning/collector.py`
- Test: `tests/test_learning_extractor.py`

- [ ] **Step 1: Add collector test**

Create `tests/test_learning_extractor.py`:

```python
from pathlib import Path
import subprocess

from agentpack.learning.collector import collect_learning_inputs


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_collect_learning_inputs_reads_task_and_changed_files(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("Add auth retry handling\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    _git(tmp_path, "add", ".agentpack/task.md", "auth.py")
    _git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "auth.py").write_text("def login():\n    return 'retry'\n", encoding="utf-8")

    collected = collect_learning_inputs(tmp_path, since=None, max_changed_files=20, max_diff_chars_per_file=500)

    assert collected.task == "Add auth retry handling"
    assert collected.changed_files["auth.py"] == "modified"
    assert "retry" in collected.diffs["auth.py"]
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_learning_extractor.py::test_collect_learning_inputs_reads_task_and_changed_files -v
```

Expected: fail because collector does not exist.

- [ ] **Step 3: Implement collector**

Create `src/agentpack/learning/collector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentpack.core import git
from agentpack.session.state import TASK_FILE


@dataclass
class LearningInputs:
    task: str
    since: str | None
    changed_files: dict[str, str]
    diffs: dict[str, str] = field(default_factory=dict)
    redaction_warnings: list[str] = field(default_factory=list)


def collect_learning_inputs(
    root: Path,
    *,
    since: str | None,
    max_changed_files: int,
    max_diff_chars_per_file: int,
) -> LearningInputs:
    task = _read_task(root)
    changed = git.diff_name_status(root, since=since)
    limited_paths = list(changed)[:max_changed_files]
    diffs: dict[str, str] = {}
    warnings: list[str] = []
    for path in limited_paths:
        diff, redaction_warnings = git.file_diff(
            root,
            path,
            since=since,
            max_chars=max_diff_chars_per_file,
        )
        diffs[path] = diff
        warnings.extend(redaction_warnings)
    return LearningInputs(
        task=task,
        since=since,
        changed_files={path: changed[path] for path in limited_paths},
        diffs=diffs,
        redaction_warnings=warnings,
    )


def _read_task(root: Path) -> str:
    path = root / TASK_FILE
    if not path.exists():
        return git.infer_task_from_git(root) if git.is_git_repo(root) else "Current work"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return lines[0] if lines else "Current work"
```

- [ ] **Step 4: Run passing test**

Run:

```bash
pytest tests/test_learning_extractor.py::test_collect_learning_inputs_reads_task_and_changed_files -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/learning/collector.py tests/test_learning_extractor.py
git commit -m "feat: collect learning report inputs"
```

---

### Task 5: Implement Deterministic Learning Extraction

**Files:**
- Create: `src/agentpack/learning/extractor.py`
- Test: `tests/test_learning_extractor.py`

- [ ] **Step 1: Add extractor behavior tests**

Append to `tests/test_learning_extractor.py`:

```python
from agentpack.learning.collector import LearningInputs
from agentpack.learning.extractor import build_learning_report


def test_build_learning_report_extracts_concepts_tests_and_quiz():
    inputs = LearningInputs(
        task="Add auth retry handling",
        since="HEAD~1",
        changed_files={
            "src/app/auth.py": "modified",
            "tests/test_auth.py": "modified",
        },
        diffs={
            "src/app/auth.py": "+ retry_count = 3\n+ raise AuthError('expired token')\n",
            "tests/test_auth.py": "+ def test_retries_expired_token():\n+     assert login() == 'ok'\n",
        },
    )

    report = build_learning_report(inputs, max_cards=5, max_quiz_questions=5)

    assert report.task == "Add auth retry handling"
    assert "authentication" in report.concepts
    assert "retry logic" in report.concepts
    assert report.tests == ["Updated tests/test_auth.py for auth behavior."]
    assert report.learning_cards
    assert report.quiz
    assert report.agent_lessons
    assert report.agent_lessons[0].evidence_files
    assert report.skill_evidence
    assert report.skill_evidence[0].task == "Add auth retry handling"
    assert "retry" in report.next_practice.lower()


def test_build_learning_report_stays_bounded():
    inputs = LearningInputs(
        task="Refactor cache config",
        since=None,
        changed_files={f"src/file_{i}.py": "modified" for i in range(20)},
        diffs={f"src/file_{i}.py": "+ cache timeout config\n" for i in range(20)},
    )

    report = build_learning_report(inputs, max_cards=3, max_quiz_questions=2)

    assert len(report.learning_cards) <= 3
    assert len(report.quiz) <= 2
    assert len(report.agent_lessons) <= 3
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_learning_extractor.py -v
```

Expected: fail because extractor does not exist.

- [ ] **Step 3: Implement extractor**

Create `src/agentpack/learning/extractor.py`:

```python
from __future__ import annotations

import re

from agentpack.learning.collector import LearningInputs
from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningReport,
    LearningSourceFile,
    QuizQuestion,
    SkillEvidence,
)


CONCEPT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("authentication", ("auth", "token", "login", "permission", "jwt")),
    ("retry logic", ("retry", "attempt", "backoff", "timeout")),
    ("caching", ("cache", "redis", "memo", "ttl")),
    ("configuration", ("config", "toml", "env", "setting")),
    ("testing", ("test_", "pytest", "assert ", "fixture")),
    ("CLI design", ("typer", "@app.command", "option", "argument")),
    ("context packing", ("pack", "context", "selected_files", "tokens")),
    ("serialization", ("json", "model_dump", "pydantic", "schema")),
]


def build_learning_report(
    inputs: LearningInputs,
    *,
    max_cards: int,
    max_quiz_questions: int,
) -> LearningReport:
    source_files = [
        LearningSourceFile(
            path=path,
            change_kind=kind,
            why=_file_why(path, kind),
            concepts=_concepts_for_text(path + "\n" + inputs.diffs.get(path, "")),
        )
        for path, kind in inputs.changed_files.items()
    ]
    concepts = _unique(
        concept
        for source in source_files
        for concept in source.concepts
    )
    summary = _summary_lines(inputs, source_files)
    decisions = _decision_lines(inputs, concepts)
    risks = _risk_lines(inputs, concepts)
    tests = _test_lines(source_files)
    cards = _learning_cards(concepts, source_files)[:max_cards]
    quiz = _quiz_questions(concepts)[:max_quiz_questions]
    agent_lessons = _agent_lessons(concepts, source_files)[:max_cards]
    skill_evidence = _skill_evidence(inputs, concepts, source_files)

    return LearningReport(
        task=inputs.task,
        scope="task",
        since=inputs.since,
        source_files=source_files,
        summary=summary,
        concepts=concepts,
        decisions=decisions,
        risks=risks,
        tests=tests,
        learning_cards=cards,
        quiz=quiz,
        agent_lessons=agent_lessons,
        skill_evidence=skill_evidence,
        next_practice=_next_practice(concepts, source_files),
    )


def _concepts_for_text(text: str) -> list[str]:
    haystack = text.lower()
    return [
        concept
        for concept, needles in CONCEPT_RULES
        if any(needle in haystack for needle in needles)
    ]


def _file_why(path: str, kind: str) -> str:
    if path.startswith("tests/") or "/test" in path:
        return f"{kind.title()} test coverage or regression behavior."
    if path.endswith(".md"):
        return f"{kind.title()} documentation or developer guidance."
    if "commands/" in path:
        return f"{kind.title()} CLI behavior."
    return f"{kind.title()} implementation behavior."


def _summary_lines(inputs: LearningInputs, source_files: list[LearningSourceFile]) -> list[str]:
    changed_count = len(source_files)
    return [
        f"Worked on: {inputs.task}",
        f"Touched {changed_count} changed file{'s' if changed_count != 1 else ''}.",
    ]


def _decision_lines(inputs: LearningInputs, concepts: list[str]) -> list[str]:
    decisions: list[str] = []
    if "CLI design" in concepts:
        decisions.append("Keep user workflow in the AgentPack CLI instead of a separate package.")
    if "testing" in concepts:
        decisions.append("Tie learning output to regression tests when test files change.")
    if not decisions:
        decisions.append("Keep learning summary local and derived from current git/task context.")
    return decisions


def _risk_lines(inputs: LearningInputs, concepts: list[str]) -> list[str]:
    risks: list[str] = []
    if "authentication" in concepts:
        risks.append("Authentication changes can fail open or mask expired-token behavior.")
    if "retry logic" in concepts:
        risks.append("Retry logic needs bounded attempts and visible failure paths.")
    if "caching" in concepts:
        risks.append("Caching changes can return stale data if invalidation is unclear.")
    if not risks:
        risks.append("Generated learning summaries can become noise if they are not specific to changed files.")
    return risks


def _test_lines(source_files: list[LearningSourceFile]) -> list[str]:
    tests = [
        f"Updated {source.path} for {'/'.join(source.concepts) or 'changed'} behavior."
        for source in source_files
        if source.path.startswith("tests/") or "/test" in source.path
    ]
    return tests or ["No changed test file detected; consider adding one regression test."]


def _learning_cards(concepts: list[str], source_files: list[LearningSourceFile]) -> list[LearningCard]:
    files_by_concept = {
        concept: [source.path for source in source_files if concept in source.concepts][:3]
        for concept in concepts
    }
    bodies = {
        "authentication": "Trace trust boundaries, token lifetime, and failure mode before changing auth code.",
        "retry logic": "Retries need a maximum attempt count, idempotent operation, and clear final error.",
        "caching": "Cache behavior is correct only when read path, write path, TTL, and invalidation are understood.",
        "configuration": "Config changes need defaults, parsing behavior, docs, and migration compatibility.",
        "testing": "Good regression tests assert observable behavior and avoid depending on implementation details.",
        "CLI design": "CLI commands should keep flags explicit, output predictable, and file writes easy to inspect.",
        "context packing": "Context packing quality depends on task clarity, changed-file detection, ranking, and token budget.",
        "serialization": "Serialized output should use stable field names and JSON-safe types.",
    }
    return [
        LearningCard(
            title=concept.title(),
            body=bodies.get(concept, f"Review how {concept} appears in the changed files."),
            files=files_by_concept.get(concept, []),
        )
        for concept in concepts
    ]


def _quiz_questions(concepts: list[str]) -> list[QuizQuestion]:
    bank = {
        "authentication": QuizQuestion(
            question="What failure mode should an auth change make explicit?",
            answer="Expired or invalid credentials should fail closed with a clear error path.",
        ),
        "retry logic": QuizQuestion(
            question="What three things make retry logic safe?",
            answer="A max attempt count, idempotent operation, and visible final failure.",
        ),
        "caching": QuizQuestion(
            question="What must be checked before changing cache behavior?",
            answer="Read path, write path, TTL, invalidation, and stale-data behavior.",
        ),
        "testing": QuizQuestion(
            question="What should a regression test assert?",
            answer="Observable behavior that would fail if the bug returned.",
        ),
        "CLI design": QuizQuestion(
            question="What makes a CLI command safe for automation?",
            answer="Explicit flags, stable output, deterministic exit codes, and inspectable writes.",
        ),
    }
    return [bank[concept] for concept in concepts if concept in bank]


def _agent_lessons(concepts: list[str], source_files: list[LearningSourceFile]) -> list[AgentLesson]:
    files_by_concept = {
        concept: [source.path for source in source_files if concept in source.concepts][:3]
        for concept in concepts
    }
    rules = {
        "authentication": (
            "When changing authentication behavior, verify fail-closed behavior, token lifetime, and regression tests.",
            "Auth mistakes can silently weaken access control.",
        ),
        "retry logic": (
            "When adding retry logic, verify max attempts, idempotency, and final error surfacing.",
            "Unbounded retries can hide permanent failures.",
        ),
        "caching": (
            "When changing cache behavior, inspect read path, write path, TTL, and invalidation together.",
            "Cache bugs often appear as stale data outside the changed file.",
        ),
        "CLI design": (
            "When editing CLI commands, update command docs and add tests for default, custom output, and JSON modes.",
            "CLI regressions are user-visible and easy to miss without invocation tests.",
        ),
        "context packing": (
            "When changing context packing, verify selected files, token budget, and receipts in tests.",
            "Packing changes can silently reduce future agent context quality.",
        ),
    }
    lessons: list[AgentLesson] = []
    for concept in concepts:
        if concept not in rules:
            continue
        rule, reason = rules[concept]
        lessons.append(AgentLesson(rule=rule, evidence_files=files_by_concept.get(concept, []), reason=reason))
    return lessons


def _skill_evidence(
    inputs: LearningInputs,
    concepts: list[str],
    source_files: list[LearningSourceFile],
) -> list[SkillEvidence]:
    return [
        SkillEvidence(
            skill=concept,
            task=inputs.task,
            evidence_files=[source.path for source in source_files if concept in source.concepts][:5],
            confidence=80 if any(concept in source.concepts for source in source_files) else 40,
        )
        for concept in concepts
    ]


def _next_practice(concepts: list[str], source_files: list[LearningSourceFile]) -> str:
    if "retry logic" in concepts:
        return "Add or review one test that proves retry attempts stop after the configured limit."
    if "CLI design" in concepts:
        return "Run the command with normal, JSON, and custom-output modes and compare behavior."
    if source_files:
        return f"Explain why {source_files[0].path} changed without looking at the diff."
    return "Write a one-paragraph summary of the task and one regression test idea."


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
```

- [ ] **Step 4: Run passing extractor tests**

Run:

```bash
pytest tests/test_learning_extractor.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/learning/extractor.py tests/test_learning_extractor.py
git commit -m "feat: build deterministic learning reports"
```

---

### Task 6: Render Markdown and JSON

**Files:**
- Create: `src/agentpack/learning/renderers.py`
- Test: `tests/test_learning_renderer.py`

- [ ] **Step 1: Add renderer tests**

Create `tests/test_learning_renderer.py`:

```python
from agentpack.learning.models import AgentLesson, LearningCard, LearningReport, LearningSourceFile, QuizQuestion, SkillEvidence
from agentpack.learning.renderers import render_agent_lessons_markdown, render_learning_markdown, learning_report_to_dict


def _report() -> LearningReport:
    return LearningReport(
        task="Add AgentPack Learn",
        scope="task",
        since="HEAD~1",
        source_files=[
            LearningSourceFile(
                path="src/agentpack/commands/learn.py",
                change_kind="added",
                why="Added CLI behavior.",
                concepts=["CLI design"],
            )
        ],
        summary=["Worked on: Add AgentPack Learn"],
        concepts=["CLI design"],
        decisions=["Keep learning in the existing CLI."],
        risks=["Summary output can become noisy."],
        tests=["Updated tests/test_learn_command.py for CLI behavior."],
        learning_cards=[
            LearningCard(
                title="CLI Design",
                body="Commands need explicit flags and predictable output.",
                files=["src/agentpack/commands/learn.py"],
            )
        ],
        quiz=[
            QuizQuestion(
                question="What makes CLI output automation-friendly?",
                answer="Stable output and deterministic exit codes.",
            )
        ],
        agent_lessons=[
            AgentLesson(
                rule="When editing CLI commands, update command docs and CLI tests.",
                evidence_files=["src/agentpack/commands/learn.py"],
                reason="CLI behavior is user-visible.",
            )
        ],
        skill_evidence=[
            SkillEvidence(
                skill="CLI design",
                task="Add AgentPack Learn",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=80,
            )
        ],
        next_practice="Run the command with Markdown and JSON output.",
    )


def test_render_learning_markdown_contains_core_sections():
    rendered = render_learning_markdown(_report())

    assert "# AgentPack Learning Summary" in rendered
    assert "## Changed Files" in rendered
    assert "`src/agentpack/commands/learn.py`" in rendered
    assert "## Learning Cards" in rendered
    assert "## Agent Lessons" in rendered
    assert "## Skill Evidence" in rendered
    assert "## Quiz" in rendered


def test_learning_report_to_dict_is_json_safe():
    payload = learning_report_to_dict(_report())

    assert payload["task"] == "Add AgentPack Learn"
    assert payload["source_files"][0]["path"] == "src/agentpack/commands/learn.py"


def test_render_agent_lessons_markdown_is_context_pack_ready():
    rendered = render_agent_lessons_markdown(_report())

    assert "# Agent Lessons" in rendered
    assert "When editing CLI commands" in rendered
    assert "`src/agentpack/commands/learn.py`" in rendered
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_learning_renderer.py -v
```

Expected: fail because renderer does not exist.

- [ ] **Step 3: Implement renderer**

Create `src/agentpack/learning/renderers.py`:

```python
from __future__ import annotations

from agentpack.learning.models import LearningReport


def learning_report_to_dict(report: LearningReport) -> dict:
    return report.model_dump(mode="json")


def render_agent_lessons_markdown(report: LearningReport) -> str:
    if not report.agent_lessons:
        return "# Agent Lessons\n\nNo agent lessons captured yet.\n"
    lines = ["# Agent Lessons", "", "Use these repo-specific lessons in future AgentPack tasks.", ""]
    for lesson in report.agent_lessons:
        lines.append(f"- {lesson.rule}")
        if lesson.evidence_files:
            lines.append("  Evidence: " + ", ".join(f"`{path}`" for path in lesson.evidence_files))
        if lesson.reason:
            lines.append(f"  Reason: {lesson.reason}")
    lines.append("")
    return "\n".join(lines)


def render_learning_markdown(report: LearningReport) -> str:
    lines: list[str] = [
        "# AgentPack Learning Summary",
        "",
        f"**Task:** {report.task}",
        f"**Scope:** {report.scope}",
    ]
    if report.since:
        lines.append(f"**Since:** `{report.since}`")
    lines.extend(["", "## Summary"])
    lines.extend(f"- {item}" for item in report.summary)
    lines.extend(["", "## Changed Files"])
    for source in report.source_files:
        concepts = ", ".join(source.concepts) if source.concepts else "none detected"
        lines.append(f"- `{source.path}` ({source.change_kind}) - {source.why} Concepts: {concepts}.")
    lines.extend(["", "## Concepts"])
    lines.extend(f"- {concept}" for concept in report.concepts)
    lines.extend(["", "## Decisions"])
    lines.extend(f"- {decision}" for decision in report.decisions)
    lines.extend(["", "## Risks"])
    lines.extend(f"- {risk}" for risk in report.risks)
    lines.extend(["", "## Tests"])
    lines.extend(f"- {test}" for test in report.tests)
    lines.extend(["", "## Skill Evidence"])
    for item in report.skill_evidence:
        files = ", ".join(f"`{path}`" for path in item.evidence_files) if item.evidence_files else "no changed file evidence"
        lines.append(f"- {item.skill}: confidence {item.confidence}; files: {files}")
    lines.extend(["", "## Learning Cards"])
    for card in report.learning_cards:
        lines.append(f"### {card.title}")
        lines.append(card.body)
        if card.files:
            lines.append("Files: " + ", ".join(f"`{path}`" for path in card.files))
        lines.append("")
    lines.extend(["## Agent Lessons"])
    for lesson in report.agent_lessons:
        lines.append(f"- {lesson.rule}")
        if lesson.evidence_files:
            lines.append("  Evidence: " + ", ".join(f"`{path}`" for path in lesson.evidence_files))
        if lesson.reason:
            lines.append(f"  Reason: {lesson.reason}")
    lines.append("")
    lines.extend(["## Quiz"])
    for idx, item in enumerate(report.quiz, start=1):
        lines.append(f"{idx}. {item.question}")
        lines.append(f"   - Answer: {item.answer}")
    lines.extend(["", "## Next Practice", report.next_practice, ""])
    return "\n".join(lines)
```

- [ ] **Step 4: Run passing tests**

Run:

```bash
pytest tests/test_learning_renderer.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/learning/renderers.py tests/test_learning_renderer.py
git commit -m "feat: render learning reports"
```

---

### Task 7: Add `agentpack learn` Command

**Files:**
- Create: `src/agentpack/commands/learn.py`
- Modify: `src/agentpack/cli.py`
- Test: `tests/test_learn_command.py`

- [ ] **Step 1: Add CLI tests**

Create `tests/test_learn_command.py`:

```python
from pathlib import Path
import json
import subprocess

from typer.testing import CliRunner

from agentpack.cli import app


runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("Add CLI learning summaries\n", encoding="utf-8")
    (tmp_path / "cli.py").write_text("import typer\n\napp = typer.Typer()\n", encoding="utf-8")
    _git(tmp_path, "add", ".agentpack/task.md", "cli.py")
    _git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "cli.py").write_text("import typer\n\napp = typer.Typer()\n@app.command()\ndef learn():\n    pass\n", encoding="utf-8")
    return tmp_path


def test_learn_writes_markdown_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0
    output = repo / ".agentpack" / "learning.md"
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "# AgentPack Learning Summary" in text
    assert "`cli.py`" in text


def test_learn_json_outputs_json_without_writing_default_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task"] == "Add CLI learning summaries"
    assert payload["source_files"][0]["path"] == "cli.py"


def test_learn_custom_output_path(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--output", ".agentpack/custom.md"])

    assert result.exit_code == 0
    assert (repo / ".agentpack" / "custom.md").exists()
```

- [ ] **Step 2: Run failing CLI tests**

Run:

```bash
pytest tests/test_learn_command.py -v
```

Expected: fail because command does not exist.

- [ ] **Step 3: Implement command**

Create `src/agentpack/commands/learn.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import typer

from agentpack.commands._shared import console, _root, _atomic_write
from agentpack.core.config import load_config
from agentpack.learning.collector import collect_learning_inputs
from agentpack.learning.extractor import build_learning_report
from agentpack.learning.renderers import learning_report_to_dict, render_learning_markdown


def register(app: typer.Typer) -> None:
    @app.command()
    def learn(
        task: str = typer.Option("auto", "--task", help="Task source. Only 'auto' is supported."),
        since: str | None = typer.Option(None, "--since", help="Git ref to compare against, e.g. HEAD~1 or main."),
        today: bool = typer.Option(False, "--today", help="Use today's work scope label for the report."),
        output: str = typer.Option("", "--output", "-o", help="Markdown output path."),
        json_output: bool = typer.Option(False, "--json", help="Print JSON to stdout instead of writing Markdown."),
    ) -> None:
        """Generate a local learning summary from current task and git changes."""
        if task != "auto":
            console.print("[red]`agentpack learn --task \"...\"` is not supported. Write .agentpack/task.md and use --task auto.[/]")
            raise typer.Exit(2)

        root = _root()
        cfg = load_config(root)
        inputs = collect_learning_inputs(
            root,
            since=since,
            max_changed_files=cfg.learning.max_changed_files,
            max_diff_chars_per_file=cfg.learning.max_diff_chars_per_file,
        )
        report = build_learning_report(
            inputs,
            max_cards=cfg.learning.max_cards,
            max_quiz_questions=cfg.learning.max_quiz_questions,
        )
        if today:
            report.scope = "today"

        if json_output:
            typer.echo(json.dumps(learning_report_to_dict(report), indent=2, sort_keys=True))
            return

        out_path = root / (output or cfg.learning.markdown_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out_path, render_learning_markdown(report))
        console.print(f"[green]✓[/] Wrote {out_path.relative_to(root)}")
```

Modify `src/agentpack/cli.py` imports:

```python
    learn,
```

Add `learn` to registration list near `summarize`:

```python
    summarize,
    learn,
    pack,
```

- [ ] **Step 4: Run passing CLI tests**

Run:

```bash
pytest tests/test_learn_command.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/commands/learn.py src/agentpack/cli.py tests/test_learn_command.py
git commit -m "feat: add agentpack learn command"
```

---

### Task 8: Ignore Generated Learning Output

**Files:**
- Modify: `src/agentpack/commands/init.py`
- Test: `tests/test_init.py`

- [ ] **Step 1: Add init ignore test**

Append to `tests/test_init.py`:

```python
def test_init_ignores_learning_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init", "--yes", "--agent", "generic"])

    assert result.exit_code == 0
    ignore_text = (tmp_path / ".agentpack" / ".gitignore").read_text(encoding="utf-8")
    assert "learning.md" in ignore_text
    assert "daily-summary.md" in ignore_text
    assert "skills-progress.json" in ignore_text
    assert "agent-lessons.md" in ignore_text
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_init.py::test_init_ignores_learning_outputs -v
```

Expected: fail if generated ignore does not include learning outputs.

- [ ] **Step 3: Update init generated ignore**

Find the `.agentpack/.gitignore` template logic in `src/agentpack/commands/init.py` and add:

```gitignore
learning.md
daily-summary.md
skills-progress.json
agent-lessons.md
```

Keep existing cache/context/snapshot ignore entries unchanged.

- [ ] **Step 4: Run passing test**

Run:

```bash
pytest tests/test_init.py::test_init_ignores_learning_outputs -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/commands/init.py tests/test_init.py
git commit -m "chore: ignore generated learning summaries"
```

---

### Task 9: Add Daily Scope Behavior

**Files:**
- Modify: `src/agentpack/commands/learn.py`
- Test: `tests/test_learn_command.py`

- [ ] **Step 1: Add daily output test**

Append to `tests/test_learn_command.py`:

```python
def test_learn_today_writes_daily_summary_path(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn", "--today"])

    assert result.exit_code == 0
    output = repo / ".agentpack" / "daily-summary.md"
    assert output.exists()
    assert "**Scope:** today" in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/test_learn_command.py::test_learn_today_writes_daily_summary_path -v
```

Expected: fail because `--today` still writes default learning path.

- [ ] **Step 3: Route `--today` to daily output**

Modify output selection in `src/agentpack/commands/learn.py`:

```python
default_output = cfg.learning.daily_output if today else cfg.learning.markdown_output
out_path = root / (output or default_output)
```

- [ ] **Step 4: Run passing command tests**

Run:

```bash
pytest tests/test_learn_command.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentpack/commands/learn.py tests/test_learn_command.py
git commit -m "feat: support daily learning summaries"
```

---

### Task 10: Persist Developer Skill Map

**Files:**
- Create: `src/agentpack/learning/skill_map.py`
- Modify: `src/agentpack/commands/learn.py`
- Test: `tests/test_learning_skill_map.py`
- Test: `tests/test_learn_command.py`

- [ ] **Step 1: Add skill map tests**

Create `tests/test_learning_skill_map.py`:

```python
import json

from agentpack.learning.models import SkillEvidence
from agentpack.learning.skill_map import update_skill_map


def test_update_skill_map_accumulates_evidence(tmp_path):
    path = tmp_path / ".agentpack" / "skills-progress.json"
    evidence = [
        SkillEvidence(
            skill="CLI design",
            task="Add AgentPack Learn",
            evidence_files=["src/agentpack/commands/learn.py"],
            confidence=80,
        )
    ]

    update_skill_map(path, evidence)
    update_skill_map(path, evidence)

    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload["skills"]["CLI design"]

    assert item["task_count"] == 2
    assert item["last_task"] == "Add AgentPack Learn"
    assert item["evidence"][0]["evidence_files"] == ["src/agentpack/commands/learn.py"]
    assert "lines_changed" not in item
    assert "productivity_score" not in item
```

Append to `tests/test_learn_command.py`:

```python
def test_learn_updates_skill_map(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0
    payload = json.loads((repo / ".agentpack" / "skills-progress.json").read_text(encoding="utf-8"))
    assert payload["skills"]
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_learning_skill_map.py tests/test_learn_command.py::test_learn_updates_skill_map -v
```

Expected: fail because skill map module and command write do not exist.

- [ ] **Step 3: Implement skill map updater**

Create `src/agentpack/learning/skill_map.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentpack.learning.models import SkillEvidence, SkillProgress


def update_skill_map(path: Path, evidence: list[SkillEvidence]) -> dict:
    payload = _read_payload(path)
    skills = payload.setdefault("skills", {})
    for item in evidence:
        current = SkillProgress.model_validate(
            skills.get(item.skill, {"skill": item.skill, "task_count": 0, "evidence": []})
        )
        current.task_count += 1
        current.last_task = item.task
        current.evidence.insert(0, item)
        current.evidence = current.evidence[:10]
        skills[item.skill] = current.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _read_payload(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "skills": {}}
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Update command to write skill map**

Modify `src/agentpack/commands/learn.py` imports:

```python
from agentpack.learning.skill_map import update_skill_map
```

After `report = build_learning_report(...)`, add:

```python
update_skill_map(root / cfg.learning.skill_map_output, report.skill_evidence)
```

- [ ] **Step 5: Run passing tests**

Run:

```bash
pytest tests/test_learning_skill_map.py tests/test_learn_command.py::test_learn_updates_skill_map -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/agentpack/learning/skill_map.py src/agentpack/commands/learn.py tests/test_learning_skill_map.py tests/test_learn_command.py
git commit -m "feat: persist developer skill map"
```

---

### Task 11: Feed Agent Lessons Into Future Context Packs

**Files:**
- Modify: `src/agentpack/core/models.py`
- Modify: `src/agentpack/application/pack_service.py`
- Modify: `src/agentpack/renderers/markdown.py`
- Modify: `src/agentpack/commands/learn.py`
- Test: `tests/test_learning_renderer.py`
- Test: `tests/test_context_pack.py`
- Test: `tests/test_learn_command.py`

- [ ] **Step 1: Add command test for agent lessons output**

Append to `tests/test_learn_command.py`:

```python
def test_learn_writes_agent_lessons(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["learn"])

    assert result.exit_code == 0
    text = (repo / ".agentpack" / "agent-lessons.md").read_text(encoding="utf-8")
    assert "# Agent Lessons" in text
    assert "Evidence:" in text
```

- [ ] **Step 2: Add context rendering test**

Append to `tests/test_context_pack.py`:

```python
from agentpack.core.models import ContextPack
from agentpack.renderers.markdown import render_generic


def test_context_pack_renders_agent_lessons():
    pack = ContextPack(
        task="Add CLI learning summaries",
        selected_files=[],
        omitted_relevant_files=[],
        receipts=[],
        changed_files=[],
        token_estimate=0,
        raw_repo_tokens=0,
        after_ignore_tokens=0,
        estimated_savings_percent=0,
        agent_lessons="- When editing CLI commands, update command docs and CLI tests.",
    )

    rendered = render_generic(pack)

    assert "## Agent Lessons From Prior Work" in rendered
    assert "update command docs" in rendered
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
pytest tests/test_learn_command.py::test_learn_writes_agent_lessons tests/test_context_pack.py::test_context_pack_renders_agent_lessons -v
```

Expected: fail because command does not write agent lessons and `ContextPack` has no `agent_lessons` field.

- [ ] **Step 4: Add `ContextPack.agent_lessons` field**

Modify `src/agentpack/core/models.py` `ContextPack`:

```python
agent_lessons: str = ""
```

- [ ] **Step 5: Load bounded lessons in pack service**

In `src/agentpack/application/pack_service.py`, add helper near other private helpers:

```python
def _read_agent_lessons(root: Path, cfg: Any, limit: int = 2000) -> str:
    if not getattr(cfg.learning, "inject_agent_lessons", True):
        return ""
    path = root / cfg.learning.agent_lessons_output
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:limit]
```

When constructing `ContextPack`, pass:

```python
agent_lessons=_read_agent_lessons(request.root, cfg),
```

- [ ] **Step 6: Render agent lessons near instructions**

Modify `src/agentpack/renderers/markdown.py` inside `render_claude` after concurrent context and before "Instructions for Claude":

```python
    if pack.agent_lessons:
        sections.append("## Agent Lessons From Prior Work")
        sections.append("")
        sections.append(pack.agent_lessons)
        sections.append("")
```

- [ ] **Step 7: Write agent lesson file from `learn`**

Modify `src/agentpack/commands/learn.py` imports:

```python
from agentpack.learning.renderers import learning_report_to_dict, render_agent_lessons_markdown, render_learning_markdown
```

After skill map update, add:

```python
agent_lessons_path = root / cfg.learning.agent_lessons_output
agent_lessons_path.parent.mkdir(parents=True, exist_ok=True)
_atomic_write(agent_lessons_path, render_agent_lessons_markdown(report))
```

- [ ] **Step 8: Run passing tests**

Run:

```bash
pytest tests/test_learn_command.py::test_learn_writes_agent_lessons tests/test_context_pack.py::test_context_pack_renders_agent_lessons tests/test_learning_renderer.py -v
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add src/agentpack/core/models.py src/agentpack/application/pack_service.py src/agentpack/renderers/markdown.py src/agentpack/commands/learn.py tests/test_context_pack.py tests/test_learn_command.py tests/test_learning_renderer.py
git commit -m "feat: feed learning lessons into agent context"
```

---

### Task 12: Add Learning Quality Gate

**Files:**
- Create: `src/agentpack/learning/quality.py`
- Modify: `src/agentpack/commands/learn.py`
- Test: `tests/test_learning_quality.py`
- Test: `tests/test_learn_command.py`

- [ ] **Step 1: Add quality gate tests**

Create `tests/test_learning_quality.py`:

```python
from agentpack.learning.models import AgentLesson, LearningCard, LearningReport, LearningSourceFile, SkillEvidence
from agentpack.learning.quality import score_learning_report


def test_quality_gate_rewards_grounded_learning_not_generic_journal():
    report = LearningReport(
        task="Add AgentPack Learn",
        scope="task",
        source_files=[
            LearningSourceFile(path="src/agentpack/commands/learn.py", change_kind="added", why="Added CLI behavior.", concepts=["CLI design"])
        ],
        summary=["Worked on: Add AgentPack Learn"],
        concepts=["CLI design"],
        decisions=["Keep learning inside the CLI."],
        risks=["Output can become generic."],
        tests=["Updated tests/test_learn_command.py for CLI behavior."],
        learning_cards=[
            LearningCard(title="CLI Design", body="Commands need predictable output.", files=["src/agentpack/commands/learn.py"])
        ],
        agent_lessons=[
            AgentLesson(rule="When editing CLI commands, update docs and CLI tests.", evidence_files=["src/agentpack/commands/learn.py"])
        ],
        skill_evidence=[
            SkillEvidence(skill="CLI design", task="Add AgentPack Learn", evidence_files=["src/agentpack/commands/learn.py"], confidence=80)
        ],
    )

    result = score_learning_report(report)

    assert result.score >= 70
    assert result.issues == []


def test_quality_gate_flags_generic_output_without_evidence():
    report = LearningReport(
        task="Fix stuff",
        scope="task",
        summary=["Worked on code."],
        learning_cards=[LearningCard(title="Development", body="You wrote code.", files=[])],
    )

    result = score_learning_report(report)

    assert result.score < 70
    assert "No changed-file evidence" in result.issues
    assert "No agent lessons" in result.issues
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_learning_quality.py -v
```

Expected: fail because quality module does not exist.

- [ ] **Step 3: Implement quality gate**

Create `src/agentpack/learning/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from agentpack.learning.models import LearningReport


@dataclass
class LearningQuality:
    score: int
    issues: list[str]


def score_learning_report(report: LearningReport) -> LearningQuality:
    score = 100
    issues: list[str] = []

    cited_files = {
        path
        for card in report.learning_cards
        for path in card.files
    } | {
        path
        for lesson in report.agent_lessons
        for path in lesson.evidence_files
    } | {
        path
        for item in report.skill_evidence
        for path in item.evidence_files
    }

    if not report.source_files or not cited_files:
        issues.append("No changed-file evidence")
        score -= 35
    if not report.concepts:
        issues.append("No concepts detected")
        score -= 15
    if not report.quiz:
        issues.append("No quiz questions")
        score -= 10
    if not report.agent_lessons:
        issues.append("No agent lessons")
        score -= 25
    if not report.skill_evidence:
        issues.append("No skill evidence")
        score -= 15
    return LearningQuality(score=max(score, 0), issues=issues)
```

- [ ] **Step 4: Surface warning in command**

Modify `src/agentpack/commands/learn.py` imports:

```python
from agentpack.learning.quality import score_learning_report
```

After report creation:

```python
quality = score_learning_report(report)
if quality.score < cfg.learning.min_groundedness_score:
    console.print(f"[yellow]Learning quality warning:[/] score {quality.score}; " + "; ".join(quality.issues))
```

- [ ] **Step 5: Run passing tests**

Run:

```bash
pytest tests/test_learning_quality.py tests/test_learn_command.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/agentpack/learning/quality.py src/agentpack/commands/learn.py tests/test_learning_quality.py tests/test_learn_command.py
git commit -m "feat: add learning quality gate"
```

---

### Task 13: Document AgentPack Learn

**Files:**
- Modify: `README.md`
- Modify: `docs/commands.md`
- Modify: `docs/configuration.md`
- Test: `tests/test_docs_links.py`

- [ ] **Step 1: Add docs content**

Add compact README section near common commands:

```markdown
### Learn from AI-assisted work

Generate local post-task learning artifacts from `.agentpack/task.md` and git changes:

```bash
agentpack learn
agentpack learn --today
agentpack learn --since main
agentpack learn --json
```

AgentPack writes developer notes to `.agentpack/learning.md` or `.agentpack/daily-summary.md`, updates `.agentpack/skills-progress.json`, and writes `.agentpack/agent-lessons.md` for future coding agents. The MVP is local-first and reuses AgentPack redaction before including diff snippets.
```

Add command row to `docs/commands.md` command map:

```markdown
| `agentpack learn` | Generate developer learning notes, skill progress, and future-agent lessons from task context and git changes |
```

Add command section:

```markdown
### `agentpack learn`

Create learning artifacts for the current task.

```bash
agentpack learn
agentpack learn --today
agentpack learn --since HEAD~1
agentpack learn --output .agentpack/review.md
agentpack learn --json
```

Default outputs:
- `.agentpack/learning.md`
- `.agentpack/daily-summary.md` with `--today`
- `.agentpack/skills-progress.json`
- `.agentpack/agent-lessons.md`

The command reads `.agentpack/task.md`, changed files, and bounded redacted diffs. It does not call a hosted service in the MVP. Agent lessons are bounded and included in future AgentPack context packs so the next AI coding agent benefits from prior repo-specific corrections.
```

Add config docs to `docs/configuration.md`:

```markdown
## Learning

```toml
[learning]
markdown_output = ".agentpack/learning.md"
daily_output = ".agentpack/daily-summary.md"
skill_map_output = ".agentpack/skills-progress.json"
agent_lessons_output = ".agentpack/agent-lessons.md"
inject_agent_lessons = true
max_changed_files = 20
max_diff_chars_per_file = 1200
max_cards = 5
max_quiz_questions = 5
min_groundedness_score = 70
```

These settings control local learning output size, destinations, future-agent context injection, and the quality warning threshold.
```

- [ ] **Step 2: Run docs checks**

Run:

```bash
pytest tests/test_docs_links.py -v
```

Expected: pass or fail only if anchors need adjustment.

- [ ] **Step 3: Fix docs check if needed**

If docs link test reports a broken anchor, change only the reported link or heading. Re-run:

```bash
pytest tests/test_docs_links.py -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/commands.md docs/configuration.md
git commit -m "docs: document agentpack learn"
```

---

### Task 14: End-to-End Verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_learning_models.py tests/test_learning_extractor.py tests/test_learning_renderer.py tests/test_learning_skill_map.py tests/test_learning_quality.py tests/test_learn_command.py tests/test_git.py::test_diff_name_status_includes_modified_and_added tests/test_git.py::test_file_diff_redacts_and_truncates -v
```

Expected: pass.

- [ ] **Step 2: Run broader command/import tests**

Run:

```bash
pytest tests/test_imports.py tests/test_init.py tests/test_docs_links.py -v
```

Expected: pass.

- [ ] **Step 3: Run local command manually**

Run:

```bash
agentpack learn --output .agentpack/learning.manual.md
```

Expected:

```text
✓ Wrote .agentpack/learning.manual.md
```

Open `.agentpack/learning.manual.md` and verify it contains:

```markdown
# AgentPack Learning Summary
## Changed Files
## Learning Cards
## Agent Lessons
## Quiz
```

- [ ] **Step 4: Verify JSON mode**

Run:

```bash
agentpack learn --json > /tmp/agentpack-learn.json
python -m json.tool /tmp/agentpack-learn.json >/dev/null
```

Expected: second command exits `0`.

- [ ] **Step 5: Run style and package smoke checks**

Run:

```bash
ruff check src/agentpack tests
python -m pytest tests/test_imports.py -v
```

Expected: pass.

- [ ] **Step 6: Review diff scope**

Run:

```bash
git diff --check
git diff --stat
```

Expected: no whitespace errors; diff limited to learning feature, command registration, config, docs, and tests.

---

## MVP Acceptance Criteria

- `agentpack learn` writes `.agentpack/learning.md`.
- `agentpack learn --today` writes `.agentpack/daily-summary.md`.
- `agentpack learn --json` prints JSON and does not require Markdown output.
- `agentpack learn --since <ref>` scopes git diff to given ref.
- Developer output includes task, changed files, concepts, decisions, risks, tests, learning cards, quiz, skill evidence, and next practice.
- Agent output writes `.agentpack/agent-lessons.md` with compact repo-specific rules grounded in changed files.
- Skill map writes `.agentpack/skills-progress.json` without productivity scoring or surveillance metrics.
- Future context packs include bounded agent lessons when `learning.inject_agent_lessons = true`.
- Quality gate warns when output is too generic or missing evidence.
- Diff snippets are bounded and redacted before analysis.
- No network/API call required.
- Generated learning files are ignored by default for new AgentPack repos.
- Docs explain privacy posture and config knobs.

## Out of Scope for This Plan

- Hosted SaaS.
- Team dashboards.
- Linear/Jira/GitHub connector ingestion.
- LLM/provider-backed summary generation.
- PR comments.
- Hosted or team-wide skill progression database.
- Manager analytics.

## Self-Review

- Spec coverage: PRD functional requirements and competitor-edge requirements map to Tasks 1-14.
- Placeholder scan: no unresolved placeholder markers, no unbounded "add tests" step, no hidden implementation step.
- Type consistency: `LearningInputs`, `LearningReport`, `LearningSourceFile`, `LearningCard`, `QuizQuestion`, `AgentLesson`, `SkillEvidence`, and `SkillProgress` names match across tasks.
- Risk: deterministic concept extraction is intentionally simple. Quality gate and file evidence reduce generic output risk; future LLM mode should use same `LearningReport` interface.
