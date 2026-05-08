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
    default_budget: int = 25000
    default_mode: str = "balanced"
    max_file_tokens: int = 4000
    include_tests: bool = True
    include_configs: bool = True
    include_receipts: bool = True


class SummaryConfig(BaseModel):
    provider: str = "offline"
    schema_version: int = 1


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
    recently_modified: float = 20
    large_unrelated_penalty: float = -50
    ignored_penalty: float = -100


class Config(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
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
default_budget = 25000   # token budget per pack
default_mode = "balanced"  # minimal | balanced | deep
max_file_tokens = 4000   # files larger than this are summarised, not inlined
include_tests = true
include_configs = true
include_receipts = true

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
recently_modified     = 20
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
