from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib
import tomli_w
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    root: str = "."
    ignore_file: str = ".agentignore"


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


class Config(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)


DEFAULT_CONFIG = Config()


def config_path(root: Path) -> Path:
    return root / ".agentpack" / "config.toml"


def load_config(root: Path) -> Config:
    path = config_path(root)
    if not path.exists():
        return DEFAULT_CONFIG
    with path.open("rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    return Config.model_validate(data)


def save_config(cfg: Config, root: Path) -> None:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump()
    with path.open("wb") as f:
        tomli_w.dump(data, f)
