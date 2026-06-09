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
