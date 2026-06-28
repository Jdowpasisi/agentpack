from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentpack.core.citations import validate_citations
from agentpack.core.models import Citation
from agentpack.learning.models import LearningReport


@dataclass
class LearningQuality:
    score: int
    issues: list[str]
    citation_coverage: float = 0.0
    invalid_citations: list[str] | None = None
    uncited_claims: list[str] | None = None


def score_learning_report(report: LearningReport, *, root: Path | None = None) -> LearningQuality:
    score = 100
    issues: list[str] = []
    citations, uncited_claims = _learning_citations(report)

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
    invalid_citations: list[str] = []
    if citations:
        if root is not None:
            validation = validate_citations(root, citations)
            invalid_citations = validation.invalid
            citation_coverage = validation.coverage
        else:
            invalid_citations = [
                f"{citation.path}: missing line"
                for citation in citations
                if citation.kind != "external" and citation.start_line is None
            ]
            citation_coverage = (
                (len(citations) - len(invalid_citations)) / len(citations)
                if citations
                else 0.0
            )
    else:
        citation_coverage = 0.0
    if not citations:
        issues.append("No claim-level citations")
        score -= 20
    if uncited_claims:
        issues.append("Uncited learning claims")
        score -= min(20, 5 * len(uncited_claims))
    if invalid_citations:
        issues.append("Invalid citations")
        score -= min(20, 5 * len(invalid_citations))
    report.citation_coverage = round(citation_coverage, 3)
    report.invalid_citations = invalid_citations
    report.uncited_claims = uncited_claims
    return LearningQuality(
        score=max(score, 0),
        issues=issues,
        citation_coverage=round(citation_coverage, 3),
        invalid_citations=invalid_citations,
        uncited_claims=uncited_claims,
    )


def _learning_citations(report: LearningReport) -> tuple[list[Citation], list[str]]:
    citations: list[Citation] = []
    uncited: list[str] = []
    for source in report.source_files:
        citations.extend(source.citations)
        if not source.citations:
            uncited.append(f"source_file:{source.path}")
    for field_name, values in (
        ("summary", report.summary),
        ("decision", report.decisions),
        ("risk", report.risks),
        ("test", report.tests),
    ):
        for index, _value in enumerate(values, start=1):
            claim_id = f"{field_name}:{index}"
            claim_citations = report.claim_citations.get(claim_id, [])
            citations.extend(claim_citations)
            if not claim_citations and report.source_files:
                uncited.append(claim_id)
    for index, card in enumerate(report.learning_cards, start=1):
        citations.extend(card.citations)
        if card.files and not card.citations:
            uncited.append(f"learning_card:{index}:{card.title}")
    for index, topic in enumerate(report.learning_topics, start=1):
        citations.extend(topic.citations)
        if topic.files and not topic.citations:
            uncited.append(f"learning_topic:{index}:{topic.title}")
    for index, lesson in enumerate(report.agent_lessons, start=1):
        citations.extend(lesson.citations)
        if lesson.evidence_files and not lesson.citations:
            uncited.append(f"agent_lesson:{index}")
    for index, item in enumerate(report.skill_evidence, start=1):
        citations.extend(item.citations)
        if item.evidence_files and not item.citations:
            uncited.append(f"skill_evidence:{index}:{item.skill}")
    return citations, uncited
