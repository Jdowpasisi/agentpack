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
