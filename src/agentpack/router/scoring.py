from __future__ import annotations

import fnmatch
import re

from agentpack.router.models import SelectedSkill, SkillArtifact

_TEST_TERMS = {"test", "tests", "pytest", "flaky", "fixture", "mock", "failing", "fail"}
_CODING_INTENT_TERMS = {
    "add", "bug", "build", "change", "code", "debug", "fix", "implement", "patch",
    "refactor", "review", "test", "update",
}
_GENERAL_CODING_SKILL_TERMS = {
    "assumption", "assumptions", "coding", "guideline", "guidelines", "mistake",
    "mistakes", "overcomplication", "refactoring", "reviewing", "success",
    "surgical", "verification", "verifiable", "writing",
}
_STOPWORDS = {
    "and", "are", "but", "for", "from", "into", "the", "this", "that", "then",
    "with", "your", "fix", "add", "make", "debug",
}


def score_skills(
    skills: list[SkillArtifact],
    *,
    task: str,
    selected_paths: list[str],
    max_selected: int,
    allow_external: bool,
    always_recommend: list[str] | None = None,
) -> tuple[list[SelectedSkill], list[str], list[SelectedSkill]]:
    pinned = _always_recommend_keys(always_recommend or [])
    scored = [
        _score_skill(skill, task=task, selected_paths=selected_paths, always_recommend=pinned)
        for skill in skills
    ]
    scored = [
        item for item in scored
        if item.score > 0 or (item.skill.side_effect_level == "external" and item.reasons)
    ]
    scored.sort(key=lambda item: (-item.score, item.skill.name.lower()))

    warnings: list[str] = []
    selected: list[SelectedSkill] = []
    for item in scored:
        if item.skill.side_effect_level == "external" and not allow_external:
            warnings.append(
                f"External side-effect skill not auto-selected: {item.skill.name} ({item.skill.path})"
            )
            continue
        if len(selected) < max_selected:
            selected.append(item)
    return selected, warnings, scored


def _score_skill(
    skill: SkillArtifact,
    *,
    task: str,
    selected_paths: list[str],
    always_recommend: set[str],
) -> SelectedSkill:
    task_terms = _terms(task)
    skill_terms = set(skill.triggers) | _terms(skill.name) | _terms(skill.description)
    selected_path_terms = set().union(*(_terms(path) for path in selected_paths)) if selected_paths else set()
    has_coding_intent = _has_coding_intent(task, selected_paths)

    reasons: list[str] = []
    score = 0.0

    keyword_matches = sorted(task_terms & skill_terms)
    if keyword_matches:
        score += min(len(keyword_matches), 8) * 10
        reasons.append(f"task keyword match: {', '.join(keyword_matches[:6])}")

    path_term_matches = sorted(selected_path_terms & skill_terms)
    if path_term_matches:
        score += min(len(path_term_matches), 6) * 6
        reasons.append(f"selected path term match: {', '.join(path_term_matches[:5])}")

    matched_globs = [
        pattern for pattern in skill.applies_to_paths
        if any(_path_matches(path, pattern) for path in selected_paths)
    ]
    if matched_globs:
        score += 24
        reasons.append(f"path hint match: {', '.join(matched_globs[:3])}")

    tool_matches = sorted(set(skill.tools_required) & (task_terms | selected_path_terms | _tool_terms(task)))
    if tool_matches:
        score += len(tool_matches) * 8
        reasons.append(f"tool match: {', '.join(tool_matches)}")

    if task_terms & _TEST_TERMS and ("pytest" in skill_terms or "test" in skill_terms):
        score += 18
        reasons.append("test task match")

    if _is_general_coding_skill(skill, skill_terms) and has_coding_intent:
        score += 22
        reasons.append("general coding guidance match")

    if _is_always_recommended(skill, always_recommend) and has_coding_intent:
        score += 36
        reasons.append("always-recommend skill")

    if skill.side_effect_level == "none":
        score += 4
        reasons.append("safe read-only skill")
    elif skill.side_effect_level == "external":
        score -= 10
        reasons.append("external side-effect penalty")

    return SelectedSkill(skill=skill, score=score, reasons=reasons)


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.replace("_", "-"))
        if token.lower() not in _STOPWORDS
    }


def _tool_terms(task: str) -> set[str]:
    terms = _terms(task)
    if terms & _TEST_TERMS:
        terms.add("pytest")
    return terms


def _is_general_coding_skill(skill: SkillArtifact, skill_terms: set[str]) -> bool:
    if skill.name.lower() in {"karpathy-guidelines", "karpathy behavioral guidelines"}:
        return True
    return len(skill_terms & _GENERAL_CODING_SKILL_TERMS) >= 4


def _always_recommend_keys(values: list[str]) -> set[str]:
    return {_normalize_skill_key(value) for value in values if value.strip()}


def _is_always_recommended(skill: SkillArtifact, always_recommend: set[str]) -> bool:
    if not always_recommend or skill.side_effect_level == "external":
        return False
    keys = {
        _normalize_skill_key(skill.name),
        _normalize_skill_key(skill.path),
        _normalize_skill_key(skill.path.rsplit("/", 1)[0]),
    }
    return bool(keys & always_recommend)


def _normalize_skill_key(value: str) -> str:
    return value.strip().lower().replace("\\", "/").rstrip("/")


def _has_coding_intent(task: str, selected_paths: list[str]) -> bool:
    task_words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", task.lower().replace("_", "-")))
    if task_words & _CODING_INTENT_TERMS:
        return True
    return any(_looks_like_code_path(path) for path in selected_paths)


def _looks_like_code_path(path: str) -> bool:
    return bool(re.search(
        r"\.(py|pyi|js|jsx|ts|tsx|go|rs|rb|php|java|kt|kts|swift|c|cc|cpp|h|hpp|cs|m|mm)$",
        path,
    ))


def _path_matches(path: str, pattern: str) -> bool:
    normalized_path = path.strip("/")
    normalized_pattern = pattern.strip("/")
    return (
        fnmatch.fnmatch(normalized_path, normalized_pattern)
        or fnmatch.fnmatch(normalized_path, f"{normalized_pattern}/**")
        or normalized_path.startswith(normalized_pattern.rstrip("/") + "/")
    )
