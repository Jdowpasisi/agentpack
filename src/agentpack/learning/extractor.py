from __future__ import annotations

import re
from collections.abc import Iterable

from agentpack.learning.collector import LearningInputs
from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningReport,
    LearningSourceFile,
    QuizQuestion,
    SkillEvidence,
)


CONCEPT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("authentication", ("auth", "token", "login", "permission", "jwt", "expired")),
    ("retry logic", ("retry", "retries", "attempt", "backoff", "timeout")),
    ("caching", ("cache", "redis", "memo", "ttl")),
    ("configuration", ("config", "toml", "env", "setting")),
    ("testing", ("test_", "pytest", "assert ", "fixture")),
    ("CLI design", ("typer", "@app.command", "option", "argument", "command")),
    ("context packing", ("pack", "context", "selected_files", "tokens")),
    ("serialization", ("json", "model_dump", "pydantic", "schema")),
]


def build_learning_report(
    inputs: LearningInputs,
    *,
    max_cards: int,
    max_quiz_questions: int,
) -> LearningReport:
    source_files = [
        LearningSourceFile(
            path=path,
            change_kind=kind,
            why=_file_why(path, kind),
            concepts=_concepts_for_text(path + "\n" + inputs.diffs.get(path, "")),
        )
        for path, kind in inputs.changed_files.items()
    ]
    concepts = _unique(
        concept
        for source in source_files
        for concept in source.concepts
    )
    summary = _summary_lines(inputs, source_files)
    decisions = _decision_lines(concepts)
    risks = _risk_lines(concepts)
    tests = _test_lines(source_files)
    cards = _learning_cards(concepts, source_files)[:max_cards]
    quiz = _quiz_questions(concepts)[:max_quiz_questions]
    agent_lessons = _agent_lessons(concepts, source_files)[:max_cards]
    skill_evidence = _skill_evidence(inputs, concepts, source_files)

    return LearningReport(
        task=inputs.task,
        scope="task",
        since=inputs.since,
        source_files=source_files,
        summary=summary,
        concepts=concepts,
        decisions=decisions,
        risks=risks,
        tests=tests,
        learning_cards=cards,
        quiz=quiz,
        agent_lessons=agent_lessons,
        skill_evidence=skill_evidence,
        next_practice=_next_practice(concepts, source_files),
    )


def _concepts_for_text(text: str) -> list[str]:
    haystack = text.lower()
    return [
        concept
        for concept, needles in CONCEPT_RULES
        if any(needle in haystack for needle in needles)
    ]


def _file_why(path: str, kind: str) -> str:
    if path.startswith("tests/") or "/test" in path:
        return f"{kind.title()} test coverage or regression behavior."
    if path.endswith(".md"):
        return f"{kind.title()} documentation or developer guidance."
    if "commands/" in path:
        return f"{kind.title()} CLI behavior."
    return f"{kind.title()} implementation behavior."


def _summary_lines(inputs: LearningInputs, source_files: list[LearningSourceFile]) -> list[str]:
    changed_count = len(source_files)
    return [
        f"Worked on: {inputs.task}",
        f"Touched {changed_count} changed file{'s' if changed_count != 1 else ''}.",
    ]


def _decision_lines(concepts: list[str]) -> list[str]:
    decisions: list[str] = []
    if "CLI design" in concepts:
        decisions.append("Keep user workflow in the AgentPack CLI instead of a separate package.")
    if "testing" in concepts:
        decisions.append("Tie learning output to regression tests when test files change.")
    if not decisions:
        decisions.append("Keep learning summary local and derived from current git/task context.")
    return decisions


def _risk_lines(concepts: list[str]) -> list[str]:
    risks: list[str] = []
    if "authentication" in concepts:
        risks.append("Authentication changes can fail open or mask expired-token behavior.")
    if "retry logic" in concepts:
        risks.append("Retry logic needs bounded attempts and visible failure paths.")
    if "caching" in concepts:
        risks.append("Caching changes can return stale data if invalidation is unclear.")
    if not risks:
        risks.append("Generated learning summaries can become noise if they are not specific to changed files.")
    return risks


def _test_lines(source_files: list[LearningSourceFile]) -> list[str]:
    tests = [
        f"Updated {source.path} for {'/'.join(source.concepts) or 'changed'} behavior."
        for source in source_files
        if source.path.startswith("tests/") or "/test" in source.path
    ]
    return tests or ["No changed test file detected; consider adding one regression test."]


def _learning_cards(concepts: list[str], source_files: list[LearningSourceFile]) -> list[LearningCard]:
    files_by_concept = _files_by_concept(concepts, source_files)
    bodies = {
        "authentication": "Trace trust boundaries, token lifetime, and failure mode before changing auth code.",
        "retry logic": "Retries need a maximum attempt count, idempotent operation, and clear final error.",
        "caching": "Cache behavior is correct only when read path, write path, TTL, and invalidation are understood.",
        "configuration": "Config changes need defaults, parsing behavior, docs, and migration compatibility.",
        "testing": "Good regression tests assert observable behavior and avoid depending on implementation details.",
        "CLI design": "CLI commands should keep flags explicit, output predictable, and file writes easy to inspect.",
        "context packing": "Context packing quality depends on task clarity, changed-file detection, ranking, and token budget.",
        "serialization": "Serialized output should use stable field names and JSON-safe types.",
    }
    return [
        LearningCard(
            title=concept.title(),
            body=bodies.get(concept, f"Review how {concept} appears in the changed files."),
            files=files_by_concept.get(concept, []),
        )
        for concept in concepts
    ]


def _quiz_questions(concepts: list[str]) -> list[QuizQuestion]:
    bank = {
        "authentication": QuizQuestion(
            question="What failure mode should an auth change make explicit?",
            answer="Expired or invalid credentials should fail closed with a clear error path.",
        ),
        "retry logic": QuizQuestion(
            question="What three things make retry logic safe?",
            answer="A max attempt count, idempotent operation, and visible final failure.",
        ),
        "caching": QuizQuestion(
            question="What must be checked before changing cache behavior?",
            answer="Read path, write path, TTL, invalidation, and stale-data behavior.",
        ),
        "testing": QuizQuestion(
            question="What should a regression test assert?",
            answer="Observable behavior that would fail if the bug returned.",
        ),
        "CLI design": QuizQuestion(
            question="What makes a CLI command safe for automation?",
            answer="Explicit flags, stable output, deterministic exit codes, and inspectable writes.",
        ),
    }
    return [bank[concept] for concept in concepts if concept in bank]


def _agent_lessons(concepts: list[str], source_files: list[LearningSourceFile]) -> list[AgentLesson]:
    files_by_concept = _files_by_concept(concepts, source_files)
    rules = {
        "authentication": (
            "When changing authentication behavior, verify fail-closed behavior, token lifetime, and regression tests.",
            "Auth mistakes can silently weaken access control.",
        ),
        "retry logic": (
            "When adding retry logic, verify max attempts, idempotency, and final error surfacing.",
            "Unbounded retries can hide permanent failures.",
        ),
        "caching": (
            "When changing cache behavior, inspect read path, write path, TTL, and invalidation together.",
            "Cache bugs often appear as stale data outside the changed file.",
        ),
        "CLI design": (
            "When editing CLI commands, update command docs and add tests for default, custom output, and JSON modes.",
            "CLI regressions are user-visible and easy to miss without invocation tests.",
        ),
        "context packing": (
            "When changing context packing, verify selected files, token budget, and receipts in tests.",
            "Packing changes can silently reduce future agent context quality.",
        ),
    }
    lessons: list[AgentLesson] = []
    for concept in concepts:
        if concept not in rules:
            continue
        rule, reason = rules[concept]
        lessons.append(AgentLesson(rule=rule, evidence_files=files_by_concept.get(concept, []), reason=reason))
    return lessons


def _skill_evidence(
    inputs: LearningInputs,
    concepts: list[str],
    source_files: list[LearningSourceFile],
) -> list[SkillEvidence]:
    return [
        SkillEvidence(
            skill=concept,
            task=inputs.task,
            evidence_files=[source.path for source in source_files if concept in source.concepts][:5],
            confidence=80 if any(concept in source.concepts for source in source_files) else 40,
        )
        for concept in concepts
    ]


def _next_practice(concepts: list[str], source_files: list[LearningSourceFile]) -> str:
    if "retry logic" in concepts:
        return "Add or review one test that proves retry attempts stop after the configured limit."
    if "CLI design" in concepts:
        return "Run the command with normal, JSON, and custom-output modes and compare behavior."
    if source_files:
        return f"Explain why {source_files[0].path} changed without looking at the diff."
    return "Write a one-paragraph summary of the task and one regression test idea."


def _files_by_concept(
    concepts: list[str],
    source_files: list[LearningSourceFile],
) -> dict[str, list[str]]:
    return {
        concept: [source.path for source in source_files if concept in source.concepts][:3]
        for concept in concepts
    }


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
