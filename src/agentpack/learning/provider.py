from __future__ import annotations

import json
import shlex
import subprocess

from pydantic import ValidationError

from agentpack.learning.collector import LearningInputs
from agentpack.learning.models import LearningReport


class LearningProviderError(RuntimeError):
    pass


def run_provider_command(command: str, report: LearningReport, *, timeout_seconds: int = 60) -> LearningReport:
    """Enrich a report through a user-supplied local command.

    The command receives the current LearningReport JSON on stdin and must return
    a JSON object with LearningReport-compatible fields on stdout.
    """
    override = _run_json_command(command, report.model_dump(mode="json"), timeout_seconds=timeout_seconds)
    if not isinstance(override, dict):
        raise LearningProviderError("Provider command must return a JSON object")
    merged = report.model_dump(mode="json")
    for key, value in override.items():
        if key in merged:
            merged[key] = value
    try:
        return LearningReport.model_validate(merged)
    except ValidationError as exc:
        raise LearningProviderError(f"Provider response did not match LearningReport schema: {exc}") from exc


def run_concept_provider_command(
    command: str,
    inputs: LearningInputs,
    report: LearningReport,
    *,
    timeout_seconds: int = 30,
) -> LearningReport:
    """Enrich learning concepts through a local IDE/LLM command.

    The command receives a bounded payload with the static report plus changed-file
    diff excerpts. It can return additive LearningReport-compatible fields and
    optional source_file_concepts/path maps.
    """
    payload = {
        "task": inputs.task,
        "since": inputs.since,
        "current_report": report.model_dump(mode="json"),
        "changed_files": [
            {
                "path": source.path,
                "change_kind": source.change_kind,
                "why": source.why,
                "detected_concepts": source.concepts,
                "diff_excerpt": inputs.diffs.get(source.path, ""),
            }
            for source in report.source_files
        ],
        "instructions": [
            "Return JSON only.",
            "Prefer source-backed concepts a developer should learn from this task.",
            "Do not invent technologies absent from task text, paths, or diff excerpts.",
            "Use source_file_concepts to map concepts back to changed files.",
        ],
        "schema": {
            "concepts": ["concept name"],
            "source_file_concepts": {"path": ["concept name"]},
            "learning_topics": [
                {
                    "title": "Concept title",
                    "why": "Why the developer should study it",
                    "prompt": "Copy-ready study prompt",
                    "files": ["path"],
                    "concepts": ["concept name"],
                }
            ],
        },
    }
    override = _run_json_command(command, payload, timeout_seconds=timeout_seconds)
    if not isinstance(override, dict):
        raise LearningProviderError("Concept provider command must return a JSON object")
    return _merge_concept_enrichment(report, override)


def _run_json_command(command: str, payload: dict, *, timeout_seconds: int) -> object:
    parts = shlex.split(command)
    if not parts:
        raise LearningProviderError("Provider command is empty")
    try:
        result = subprocess.run(
            parts,
            input=json.dumps(payload, sort_keys=True),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LearningProviderError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LearningProviderError(detail or f"Provider command exited {result.returncode}")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise LearningProviderError(f"Provider command returned invalid JSON: {exc}") from exc


def _merge_concept_enrichment(report: LearningReport, override: dict) -> LearningReport:
    merged = report.model_dump(mode="json")
    merged["concepts"] = _unique_strings([*merged.get("concepts", []), *_string_list(override.get("concepts"))])
    source_file_concepts = _source_file_concepts(override.get("source_file_concepts") or override.get("file_concepts"))
    if source_file_concepts:
        for source in merged.get("source_files", []):
            path = source.get("path", "")
            source["concepts"] = _unique_strings([*source.get("concepts", []), *source_file_concepts.get(path, [])])
    for field in (
        "summary",
        "decisions",
        "risks",
        "tests",
        "learning_topics",
        "learning_cards",
        "quiz",
        "agent_lessons",
        "skill_evidence",
    ):
        if isinstance(override.get(field), list):
            merged[field] = _unique_json_items([*merged.get(field, []), *override[field]])
    if isinstance(override.get("next_practice"), str) and override["next_practice"].strip():
        merged["next_practice"] = override["next_practice"].strip()
    try:
        return LearningReport.model_validate(merged)
    except ValidationError as exc:
        raise LearningProviderError(f"Concept provider response did not match LearningReport schema: {exc}") from exc


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _source_file_concepts(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for path, concepts in value.items():
        if isinstance(path, str):
            normalized = _string_list(concepts)
            if normalized:
                result[path] = normalized
    return result


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _unique_json_items(values: list[object]) -> list[object]:
    seen: set[str] = set()
    result: list[object] = []
    for value in values:
        key = json.dumps(value, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
