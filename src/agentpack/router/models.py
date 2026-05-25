from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SideEffectLevel = Literal["none", "file_write", "command", "external"]


class SkillArtifact(BaseModel):
    name: str
    source: str
    path: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    tools_required: list[str] = Field(default_factory=list)
    side_effect_level: SideEffectLevel = "none"
    applies_to_paths: list[str] = Field(default_factory=list)
    raw_text: str = ""


class RuleArtifact(BaseModel):
    name: str
    source: str
    path: str
    scope_paths: list[str] = Field(default_factory=list)
    priority: int = 50
    description: str = ""
    raw_text: str = ""


class SelectedSkill(BaseModel):
    skill: SkillArtifact
    score: float
    reasons: list[str] = Field(default_factory=list)


class AppliedRule(BaseModel):
    rule: RuleArtifact
    reasons: list[str] = Field(default_factory=list)


class CommandSuggestion(BaseModel):
    command: str
    reason: str
    source: str
    side_effect_level: Literal["command"] = "command"


class SkillInventory(BaseModel):
    version: int = 1
    skills: list[SkillArtifact] = Field(default_factory=list)
    rules: list[RuleArtifact] = Field(default_factory=list)


class RouteResult(BaseModel):
    task: str
    selected_files: list[dict] = Field(default_factory=list)
    selected_skills: list[SelectedSkill] = Field(default_factory=list)
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    suggested_commands: list[CommandSuggestion] = Field(default_factory=list)
    safety_warnings: list[str] = Field(default_factory=list)
    agent_prompt: str = ""


class RouteExplanation(RouteResult):
    skill_scores: list[SelectedSkill] = Field(default_factory=list)
