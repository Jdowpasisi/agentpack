from __future__ import annotations

import re
from collections.abc import Iterable

from agentpack.core.models import Citation
from agentpack.learning.collector import LearningInputs
from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningReport,
    LearningSourceFile,
    LearningTopic,
    QuizQuestion,
    SkillEvidence,
)


CONCEPT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("mcp", ("mcp", "model context protocol", "retrieve_context")),
    ("authentication", ("auth", "token", "login", "permission", "jwt", "expired")),
    ("retry logic", ("retry", "retries", "attempt", "backoff", "timeout")),
    ("caching", ("cache", "redis", "memo", "ttl")),
    ("rate limiting", ("rate limit", "rate_limit", "ratelimit", "limiter", "throttle", "quota", "429")),
    ("configuration", ("config", "toml", "env", "setting")),
    ("testing", ("test_", "pytest", "assert ", "fixture")),
    ("CLI design", ("typer", "@app.command", "option", "argument", "command")),
    ("context packing", ("pack", "context", "selected_files", "tokens")),
    ("serialization", ("json", "model_dump", "pydantic", "schema")),
]


def build_learning_report(
    inputs: LearningInputs,
    *,
    max_cards: int = 5,
    max_quiz_questions: int = 5,
) -> LearningReport:
    source_files = [
        LearningSourceFile(
            path=path,
            change_kind=kind,
            why=_file_why(path, kind),
            concepts=_concepts_for_text(path + "\n" + inputs.diffs.get(path, "")),
            citations=[_source_citation(path, f"source:{path}")],
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
    claim_citations = _report_claim_citations(
        summary=summary,
        decisions=decisions,
        risks=risks,
        tests=tests,
        concepts=concepts,
        source_files=source_files,
    )
    topics = _learning_topics(inputs, concepts, source_files)[:max_cards]
    cards = _learning_cards(concepts, source_files)[:max_cards]
    quiz = _quiz_questions(concepts)[:max_quiz_questions]
    agent_lessons = _agent_lessons(concepts, source_files)[:max_cards]
    skill_evidence = _skill_evidence(inputs, concepts, source_files)
    selected = set(inputs.selected_files)
    changed = set(inputs.changed_files)

    return LearningReport(
        task=inputs.task,
        scope="task",
        since=inputs.since,
        issue_references=inputs.issue_references,
        issue_reference_details=inputs.issue_reference_details,
        source_files=source_files,
        summary=summary,
        concepts=concepts,
        decisions=decisions,
        risks=risks,
        tests=tests,
        claim_citations=claim_citations,
        learning_topics=topics,
        learning_cards=cards,
        quiz=quiz,
        agent_lessons=agent_lessons,
        skill_evidence=skill_evidence,
        next_practice=_next_practice(concepts, source_files),
        selected_hits=sorted(changed & selected),
        selected_misses=sorted(changed - selected) if selected else [],
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
    if "rate limiting" in concepts:
        risks.append("Rate limiting changes need clear identity keys, windows, limits, and failure behavior.")
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


def _report_claim_citations(
    *,
    summary: list[str],
    decisions: list[str],
    risks: list[str],
    tests: list[str],
    concepts: list[str],
    source_files: list[LearningSourceFile],
) -> dict[str, list[Citation]]:
    paths = [source.path for source in source_files]
    files_by_concept = _files_by_concept(concepts, source_files)
    citations: dict[str, list[Citation]] = {}
    for index, _claim in enumerate(summary, start=1):
        citations[f"summary:{index}"] = _citations_for_files(paths[:5], f"summary:{index}")
    for index, claim in enumerate(decisions, start=1):
        claim_paths = _claim_paths(claim, concepts, files_by_concept) or paths[:3]
        citations[f"decision:{index}"] = _citations_for_files(claim_paths, f"decision:{index}")
    for index, claim in enumerate(risks, start=1):
        claim_paths = _claim_paths(claim, concepts, files_by_concept) or paths[:3]
        citations[f"risk:{index}"] = _citations_for_files(claim_paths, f"risk:{index}")
    for index, claim in enumerate(tests, start=1):
        test_paths = [path for path in paths if path.startswith("tests/") or "/test" in path]
        claim_paths = test_paths or paths[:3]
        citations[f"test:{index}"] = _citations_for_files(claim_paths, f"test:{index}")
    return {key: value for key, value in citations.items() if value}


def _claim_paths(
    claim: str,
    concepts: list[str],
    files_by_concept: dict[str, list[str]],
) -> list[str]:
    lowered = claim.lower()
    for concept in concepts:
        if concept.lower() in lowered or any(part in lowered for part in concept.lower().split()):
            return files_by_concept.get(concept, [])
    return []


def _learning_cards(concepts: list[str], source_files: list[LearningSourceFile]) -> list[LearningCard]:
    files_by_concept = _files_by_concept(concepts, source_files)
    bodies = {
        "authentication": "Trace trust boundaries, token lifetime, and failure mode before changing auth code.",
        "retry logic": "Retries need a maximum attempt count, idempotent operation, and clear final error.",
        "caching": "Cache behavior is correct only when read path, write path, TTL, and invalidation are understood.",
        "rate limiting": "Rate limiting needs a stable identity key, bounded window, storage semantics, and visible 429 behavior.",
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
            citations=_citations_for_files(files_by_concept.get(concept, []), f"learning-card:{concept}"),
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
        "rate limiting": QuizQuestion(
            question="What makes rate limiting correct and debuggable?",
            answer="A clear identity key, window algorithm, limit, storage behavior, and observable 429 response.",
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
        "rate limiting": (
            "When implementing rate limits, verify identity keys, window semantics, storage TTLs, and 429 tests.",
            "Rate limits can fail open, over-block users, or leak under concurrent requests.",
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
        files = files_by_concept.get(concept, [])
        lessons.append(
            AgentLesson(
                rule=rule,
                evidence_files=files,
                reason=reason,
                citations=_citations_for_files(files, f"agent-lesson:{concept}"),
            )
        )
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
            citations=_citations_for_files(
                [source.path for source in source_files if concept in source.concepts][:5],
                f"skill-evidence:{concept}",
            ),
        )
        for concept in concepts
    ]


def _next_practice(concepts: list[str], source_files: list[LearningSourceFile]) -> str:
    if "rate limiting" in concepts:
        return "Explain the rate-limit identity key, window, storage TTL, and one 429 regression test."
    if "retry logic" in concepts:
        return "Add or review one test that proves retry attempts stop after the configured limit."
    if "CLI design" in concepts:
        return "Run the command with normal, JSON, and custom-output modes and compare behavior."
    if source_files:
        return f"Explain why {source_files[0].path} changed without looking at the diff."
    return "Write a one-paragraph summary of the task and one regression test idea."


def _learning_topics(
    inputs: LearningInputs,
    concepts: list[str],
    source_files: list[LearningSourceFile],
) -> list[LearningTopic]:
    files_by_concept = _files_by_concept(concepts, source_files)
    topics: list[LearningTopic] = []
    if "rate limiting" in concepts:
        topic_concepts = ["rate limiting"]
        title = "Implementing Rate Limits"
        why = "Study how to enforce request quotas without failing open or blocking valid users."
        files = files_by_concept.get("rate limiting", [])
        if "caching" in concepts or _mentions_any(source_files, ("redis", "ttl")):
            topic_concepts.append("caching")
            title = "Implementing Rate Limits With Redis"
            why = "Study Redis-backed counters, windows, TTLs, and atomic updates for rate limiting."
            files = _unique([*files, *files_by_concept.get("caching", [])])[:5]
        topics.append(_topic(inputs, title=title, why=why, concepts=topic_concepts, files=files))

    templates = {
        "authentication": ("Authentication Failure Modes", "Study how auth changes fail closed, handle expired tokens, and preserve trust boundaries."),
        "retry logic": ("Safe Retry Logic", "Study bounded retries, idempotency, backoff, and final failure visibility."),
        "caching": ("Cache Correctness", "Study read/write paths, TTLs, invalidation, and stale-data behavior."),
        "configuration": ("Configuration Design", "Study defaults, parsing, migration compatibility, and documentation."),
        "testing": ("Regression Test Design", "Study how to turn recent code changes into behavior-focused regression tests."),
        "CLI design": ("CLI Workflow Design", "Study predictable flags, outputs, exit codes, and automation-safe command behavior."),
        "context packing": ("Context Packing Quality", "Study how task clarity, changed files, ranking, and token budgets shape agent context."),
        "serialization": ("Stable Serialization", "Study schema evolution, JSON-safe types, and stable field names."),
    }
    existing = {topic.title for topic in topics}
    for concept in concepts:
        if concept in {"rate limiting"}:
            continue
        title, why = templates.get(concept, (concept.title(), f"Study how {concept} appears in the recent task."))
        if title in existing:
            continue
        topics.append(_topic(inputs, title=title, why=why, concepts=[concept], files=files_by_concept.get(concept, [])))
        existing.add(title)
    return topics


def _topic(
    inputs: LearningInputs,
    *,
    title: str,
    why: str,
    concepts: list[str],
    files: list[str],
) -> LearningTopic:
    evidence = files[:5]
    prompt = (
        f"Teach me {title.lower()} using this recent coding task as context.\n"
        f"Task: {inputs.task}\n"
        f"Concepts detected: {', '.join(concepts)}\n"
        f"Evidence files: {', '.join(evidence) or 'none'}\n\n"
        "Explain the core idea, common implementation choices, failure modes, testing strategy, "
        "and a small checklist I can apply before shipping. Do not assume code that is not implied by the task or evidence files."
    )
    return LearningTopic(
        title=title,
        why=why,
        prompt=prompt,
        files=evidence,
        concepts=concepts,
        citations=_citations_for_files(evidence, f"learning-topic:{title}"),
    )


def _source_citation(path: str, claim_id: str) -> Citation:
    return Citation(path=path, start_line=1, end_line=1, kind="summary", claim_id=claim_id, note="changed-file source")


def _citations_for_files(paths: list[str], claim_prefix: str) -> list[Citation]:
    return [_source_citation(path, f"{claim_prefix}:{index}") for index, path in enumerate(paths, start=1)]


def _mentions_any(source_files: list[LearningSourceFile], terms: tuple[str, ...]) -> bool:
    haystack = "\n".join([source.path + " " + " ".join(source.concepts) for source in source_files]).lower()
    return any(term in haystack for term in terms)


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
