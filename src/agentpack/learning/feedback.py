from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from agentpack.learning.models import FeedbackSignal, FeedbackSummary, LearningReport


def record_learning_feedback(
    path: Path,
    report: LearningReport,
    feedback: str,
    note: str = "",
    target: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = FeedbackSignal(
        created_at=datetime.now(timezone.utc).isoformat(),
        task=report.task,
        scope=report.scope,
        feedback=feedback,
        note=note,
        target=target,
        concepts=report.concepts,
        source_files=[source.path for source in report.source_files],
    ).model_dump(mode="json")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def load_feedback_summary(path: Path) -> FeedbackSummary:
    summary = FeedbackSummary()
    if not path.exists():
        return summary
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            signal = FeedbackSignal.model_validate_json(line)
        except (ValidationError, ValueError):
            continue
        _apply_signal(summary, signal)
    return summary


def apply_feedback_to_report(report: LearningReport, summary: FeedbackSummary) -> LearningReport:
    if not _has_feedback(summary):
        return report

    rename_map = {old.lower(): new for old, new in summary.skill_renames.items()}
    merge_map = {old.lower(): new for old, new in summary.skill_merges.items()}
    suppressed_skills = {skill.lower() for skill in summary.suppressed_skills}
    not_helpful = {concept.lower() for concept in summary.not_helpful_concepts}
    suppressed = suppressed_skills | not_helpful

    for source in report.source_files:
        source.concepts = [_normalize_concept(concept, rename_map, merge_map) for concept in source.concepts]
        source.concepts = [concept for concept in source.concepts if concept.lower() not in suppressed]

    report.concepts = [_normalize_concept(concept, rename_map, merge_map) for concept in report.concepts]
    report.concepts = _dedupe([concept for concept in report.concepts if concept.lower() not in suppressed])

    report.learning_cards = [
        card
        for card in report.learning_cards
        if card.title.lower() not in suppressed
        and not any(concept.lower() == card.title.lower() for concept in summary.not_helpful_concepts)
    ]
    for card in report.learning_cards:
        normalized = _normalize_concept(card.title, rename_map, merge_map)
        if normalized != card.title:
            card.title = normalized
        if card.title.lower() in {item.lower() for item in summary.helpful_concepts}:
            card.body = f"{card.body} Prior feedback marked this concept useful; keep practicing it with changed-file evidence."

    report.agent_lessons = [
        lesson
        for lesson in report.agent_lessons
        if not _lesson_suppressed(lesson.rule, summary)
    ]
    for lesson in report.agent_lessons:
        if _lesson_helpful(lesson.rule, report.concepts, summary):
            lesson.status = "accepted"
            lesson.confidence = min(100, max(lesson.confidence, 90))

    for item in report.skill_evidence:
        item.skill = _normalize_concept(item.skill, rename_map, merge_map)
        if item.skill.lower() in {concept.lower() for concept in summary.helpful_concepts}:
            item.confidence = min(100, item.confidence + 10)
    report.skill_evidence = [
        item for item in report.skill_evidence if item.skill.lower() not in suppressed
    ]
    return report


def _apply_signal(summary: FeedbackSummary, signal: FeedbackSignal) -> None:
    target = signal.target.strip()
    target_kind, _, target_value = target.partition(":")
    normalized_feedback = signal.feedback.strip().lower()
    if normalized_feedback == "helpful":
        summary.helpful_concepts.update(signal.concepts)
        if signal.note:
            summary.accepted_notes.append(signal.note)
    elif normalized_feedback == "not-helpful":
        summary.not_helpful_concepts.update(signal.concepts)

    if target_kind == "skill" and target_value:
        if normalized_feedback == "not-helpful":
            summary.suppressed_skills.add(target_value)
        elif normalized_feedback == "helpful":
            summary.helpful_concepts.add(target_value)
    elif target_kind == "lesson" and target_value and normalized_feedback == "not-helpful":
        summary.suppressed_lesson_terms.add(target_value)
    elif target_kind == "rename" and "=>" in target_value:
        old, new = [part.strip() for part in target_value.split("=>", 1)]
        if old and new:
            summary.skill_renames[old] = new
    elif target_kind == "merge" and "=>" in target_value:
        old, new = [part.strip() for part in target_value.split("=>", 1)]
        if old and new:
            summary.skill_merges[old] = new


def _has_feedback(summary: FeedbackSummary) -> bool:
    return bool(
        summary.helpful_concepts
        or summary.not_helpful_concepts
        or summary.suppressed_skills
        or summary.suppressed_lesson_terms
        or summary.skill_renames
        or summary.skill_merges
    )


def _normalize_concept(concept: str, renames: dict[str, str], merges: dict[str, str]) -> str:
    key = concept.lower()
    return merges.get(key) or renames.get(key) or concept


def _lesson_suppressed(rule: str, summary: FeedbackSummary) -> bool:
    lower = rule.lower()
    return any(term.lower() in lower for term in summary.suppressed_lesson_terms)


def _lesson_helpful(rule: str, concepts: list[str], summary: FeedbackSummary) -> bool:
    lower_rule = rule.lower()
    helpful = {concept.lower() for concept in summary.helpful_concepts}
    for concept in concepts:
        lower_concept = concept.lower()
        if lower_concept not in helpful:
            continue
        if lower_concept in lower_rule:
            return True
        if any(part and part in lower_rule for part in lower_concept.split()):
            return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
