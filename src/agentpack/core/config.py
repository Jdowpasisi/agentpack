from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
import tomli_w
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    root: str = "."
    ignore_file: str = ".agentignore"
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)


class ContextConfig(BaseModel):
    default_budget: int = 40000
    default_mode: str = "balanced"
    max_file_tokens: int = 4000
    incremental_scan: bool = True
    full_scan_interval_seconds: int = 3600
    max_incremental_changed_files: int = 200
    min_summary_score: float = 60
    max_summary_files_minimal: int = 15
    max_summary_files_balanced: int = 40
    max_summary_files_deep: int = 0
    include_tests: bool = True
    include_configs: bool = True
    include_receipts: bool = True


class LiteContextConfig(BaseModel):
    budget: int = 8000
    max_selected_files: int = 12
    max_omitted_files: int = 5
    max_stubs: int = 8
    summary_chars: int = 500


class SummaryConfig(BaseModel):
    provider: str = "offline"
    schema_version: int = 2


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


class HooksConfig(BaseModel):
    task_switch_detection: bool = True
    task_switch_min_terms: int = 1
    blocking_task_refresh: bool = True


class SkillsConfig(BaseModel):
    paths: list[str] = Field(default_factory=lambda: [
        "skills",
        ".claude-plugin",
        ".claude/skills",
        "~/.claude/skills",
        "~/.codex/skills",
        "~/.agents/skills",
        ".agentpack/skills",
        ".cursor/rules",
    ])
    max_selected: int = 3
    always_recommend: list[str] = Field(default_factory=lambda: ["karpathy-guidelines"])
    allow_external_side_effects: bool = False


class AgentConfig(BaseModel):
    output: str
    patch_claude_md: bool = False


class AgentsConfig(BaseModel):
    claude: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            output=".agentpack/context.claude.md",
            patch_claude_md=True,
        )
    )
    generic: AgentConfig = Field(
        default_factory=lambda: AgentConfig(output=".agentpack/context.md")
    )


class ScoringWeights(BaseModel):
    """Configurable scoring weights. All values are additive points."""
    modified: float = 100
    staged: float = 90
    filename_keyword: float = 80
    symbol_keyword: float = 70
    content_keyword_per_hit: float = 10
    content_keyword_max: float = 60
    direct_dep: float = 50
    reverse_dep: float = 40
    related_test: float = 35
    config_file: float = 25
    knowledge_file: float = 30
    implementation_role: float = 35
    cross_layer_related: float = 30
    co_changed: float = 28
    recall_neighbor: float = 24
    workspace_match: float = 32
    weak_filename_match_penalty: float = -45
    recently_modified: float = 20
    churn_high: float = 15   # file appears in top 10% by churn
    large_unrelated_penalty: float = -50
    ignored_penalty: float = -100


class Config(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    context_lite: LiteContextConfig = Field(default_factory=LiteContextConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)


DEFAULT_CONFIG = Config()

CONFIG_TEMPLATE = """\
[project]
# Restrict packing to these glob patterns (empty = all files).
# Example: include_globs = ["app/**", "packages/core/**"]
include_globs = []
# Always exclude these patterns on top of .agentignore.
# Example: exclude_globs = ["migrations/**", "generated/**", "snapshots/**"]
exclude_globs = []

[context]
default_budget = 40000   # token budget per pack
default_mode = "balanced"  # minimal | balanced | deep
max_file_tokens = 4000   # files larger than this are summarised, not inlined
incremental_scan = true  # reuse previous snapshot and re-hash only dirty paths when safe
full_scan_interval_seconds = 3600  # periodic correctness backstop
max_incremental_changed_files = 200  # fall back to full scan above this many dirty paths
min_summary_score = 60   # unchanged summary files below this score are excluded
max_summary_files_minimal = 15   # 0 = no cap
max_summary_files_balanced = 40  # 0 = no cap
max_summary_files_deep = 0       # deep mode stays uncapped
include_tests = true
include_configs = true
include_receipts = true

[context_lite]
budget = 8000
max_selected_files = 12
max_omitted_files = 5
max_stubs = 8
summary_chars = 500

[summary]
provider = "offline"
schema_version = 2

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

[hooks]
# Claude UserPromptSubmit can detect a clearly different coding prompt,
# update .agentpack/task.md, and repack even if files did not change.
task_switch_detection = true
task_switch_min_terms = 1
# Block once on task switches so the first prompt sees fresh top-file hints.
blocking_task_refresh = true

[skills]
# Skill/rule sources used by `agentpack route` and MCP `route_task`.
paths = ["skills", ".claude-plugin", ".claude/skills", "~/.claude/skills", "~/.codex/skills", "~/.agents/skills", ".agentpack/skills", ".cursor/rules"]
max_selected = 3
always_recommend = ["karpathy-guidelines"]
allow_external_side_effects = false

[scoring]
# Scoring weights — higher wins budget allocation.
# Tune these to make agentpack favour your team's file layout.
modified              = 100
staged                = 90
filename_keyword      = 80
symbol_keyword        = 70
content_keyword_per_hit = 10
content_keyword_max   = 60
direct_dep            = 50
reverse_dep           = 40
related_test          = 35
config_file           = 25
knowledge_file        = 30
implementation_role   = 35
cross_layer_related   = 30
co_changed            = 28
recall_neighbor       = 24
workspace_match       = 32
weak_filename_match_penalty = -45
recently_modified     = 20
churn_high            = 15
large_unrelated_penalty = -50
ignored_penalty       = -100
"""


def config_path(root: Path) -> Path:
    return root / ".agentpack" / "config.toml"


def load_config(root: Path) -> Config:
    path = config_path(root)
    if not path.exists():
        return DEFAULT_CONFIG
    try:
        with path.open("rb") as f:
            data: dict[str, Any] = tomllib.load(f)
        return Config.model_validate(data)
    except Exception:
        import warnings
        warnings.warn(
            f"Failed to parse {path} — using defaults. Fix or delete the file.",
            stacklevel=2,
        )
        return DEFAULT_CONFIG


def save_config(cfg: Config, root: Path) -> None:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump()
    with path.open("wb") as f:
        tomli_w.dump(data, f)
