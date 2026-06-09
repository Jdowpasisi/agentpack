from __future__ import annotations

from agentpack.learning.models import AgentLesson, FeedbackSummary, LearningReport


def rank_agent_lessons(
    report: LearningReport,
    feedback: FeedbackSummary,
    *,
    limit: int,
) -> list[AgentLesson]:
    lessons = [
        lesson
        for lesson in report.agent_lessons
        if not _suppressed(lesson, feedback)
    ]
    lessons.sort(key=lambda lesson: _score(lesson, report, feedback), reverse=True)
    return lessons[:limit]


def _score(lesson: AgentLesson, report: LearningReport, feedback: FeedbackSummary) -> int:
    score = lesson.confidence
    rule = lesson.rule.lower()
    if lesson.status == "accepted":
        score += 30
    if lesson.evidence_files:
        score += 15
    for concept in report.concepts:
        if concept.lower() in rule:
            score += 10
    for concept in feedback.helpful_concepts:
        if concept.lower() in rule:
            score += 20
    return score


def _suppressed(lesson: AgentLesson, feedback: FeedbackSummary) -> bool:
    rule = lesson.rule.lower()
    return any(term.lower() in rule for term in feedback.suppressed_lesson_terms)
