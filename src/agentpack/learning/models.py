from __future__ import annotations

from datetime import datetime, timezone

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


class LearningTopic(BaseModel):
    title: str
    why: str
    prompt: str
    files: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    question: str
    answer: str


class AgentLesson(BaseModel):
    rule: str
    evidence_files: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: int = 70
    status: str = "generated"
    last_seen: str = ""


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
    aliases: list[str] = Field(default_factory=list)
    confidence: int = 0
    first_seen: str = ""
    last_seen: str = ""
    source_paths: list[str] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    accepted_corrections: list[str] = Field(default_factory=list)
    suppressed: bool = False


class FeedbackSignal(BaseModel):
    feedback: str
    target: str = ""
    note: str = ""
    task: str = ""
    scope: str = ""
    concepts: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FeedbackSummary(BaseModel):
    helpful_concepts: set[str] = Field(default_factory=set)
    not_helpful_concepts: set[str] = Field(default_factory=set)
    suppressed_skills: set[str] = Field(default_factory=set)
    suppressed_lesson_terms: set[str] = Field(default_factory=set)
    skill_renames: dict[str, str] = Field(default_factory=dict)
    skill_merges: dict[str, str] = Field(default_factory=dict)
    accepted_notes: list[str] = Field(default_factory=list)


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
    learning_topics: list[LearningTopic] = Field(default_factory=list)
    learning_cards: list[LearningCard] = Field(default_factory=list)
    quiz: list[QuizQuestion] = Field(default_factory=list)
    agent_lessons: list[AgentLesson] = Field(default_factory=list)
    skill_evidence: list[SkillEvidence] = Field(default_factory=list)
    next_practice: str = ""
