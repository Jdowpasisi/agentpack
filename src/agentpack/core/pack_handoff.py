from __future__ import annotations

from typing import Any, Literal

from agentpack.core.models import ContextPack

NextAction = Literal[
    "ready_to_inspect_selected",
    "inspect_omitted_first",
    "refresh_context",
    "deepen_pack",
    "run_direct_search",
]


def build_pack_handoff(pack: ContextPack) -> dict[str, Any]:
    """Return a compact operational receipt for agents before editing.

    The receipt intentionally avoids correctness/confidence claims. It only
    summarizes signals AgentPack already computed and recommends the next
    inspection step before code changes.
    """
    high_risk_omitted = [item for item in pack.omitted_relevant_files if item.risk == "high"]
    stale = pack.stale or bool(pack.freshness_warnings)
    budget_pressure = pack.budget > 0 and pack.token_estimate >= int(pack.budget * 0.95)

    if stale:
        action: NextAction = "refresh_context"
        reason = "pack is stale or has freshness warnings"
    elif high_risk_omitted:
        action = "inspect_omitted_first"
        reason = "high-risk omitted relevant files matched the task"
    elif budget_pressure:
        action = "deepen_pack"
        reason = "pack rendered close to the token budget"
    elif not pack.selected_files:
        action = "run_direct_search"
        reason = "no selected files were included in the pack"
    else:
        action = "ready_to_inspect_selected"
        reason = "selected files are available and no refresh or omitted-file gate fired"

    return {
        "recommended_action": action,
        "reason": reason,
        "task": pack.task,
        "task_hash": pack.freshness.get("packed_task_hash") or pack.freshness.get("task_hash") or "",
        "context_path": pack.freshness.get("context_path", ""),
        "git_sha": pack.freshness.get("git_sha", ""),
        "git_branch": pack.freshness.get("git_branch", ""),
        "budget": {
            "target_tokens": pack.budget,
            "rendered_tokens": pack.token_estimate,
            "pressure": budget_pressure,
        },
        "selected": {
            "files": len(pack.selected_files),
            "tests": sum(1 for item in pack.selected_files if _looks_like_test(item.path)),
        },
        "omitted_relevant": {
            "files": len(pack.omitted_relevant_files),
            "high_risk": len(high_risk_omitted),
            "top": [item.path for item in high_risk_omitted[:5]],
        },
        "freshness": {
            "refresh_required": stale,
            "warnings": list(pack.freshness_warnings),
        },
        "suggested_checks": [],
    }


def _looks_like_test(path: str) -> bool:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return lower.startswith(("tests/", "test/")) or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
