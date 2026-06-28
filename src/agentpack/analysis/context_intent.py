from __future__ import annotations

import re
from typing import Literal


ContextIntent = Literal["coding_task", "review", "share", "repo_overview", "audit"]

_AUDIT_TERMS = ("audit", "security review", "risk review", "architecture review")
_REVIEW_TERMS = ("review", "pr", "pull request", "code review")
_SHARE_TERMS = ("share", "handoff", "promptable artifact", "broad context")
_OVERVIEW_TERMS = ("repo overview", "repository overview", "explain repo", "understand repo", "map repo")


def infer_context_intent(task: str, *, task_mode: str | None = None) -> ContextIntent:
    text = " ".join((task or "").lower().replace("_", " ").replace("-", " ").split())
    mode = (task_mode or "").lower()
    if mode == "pr_review" or _has_any(text, _REVIEW_TERMS):
        if _has_any(text, _AUDIT_TERMS):
            return "audit"
        return "review"
    if _has_any(text, _AUDIT_TERMS):
        return "audit"
    if _has_any(text, _SHARE_TERMS):
        return "share"
    if _has_any(text, _OVERVIEW_TERMS):
        return "repo_overview"
    return "coding_task"


def broad_context_enabled(config_value: str, intent: ContextIntent) -> bool:
    value = (config_value or "auto").strip().lower()
    if value == "off":
        return False
    if value == "on":
        return True
    return intent in {"review", "share", "repo_overview", "audit"}


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text) for term in terms)
