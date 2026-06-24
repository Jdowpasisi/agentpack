from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from agentpack.core.models import ContextPack, OmittedRelevantFile

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
    omitted_relevant_files = pack.pack_handoff_omitted_relevant_files or pack.omitted_relevant_files
    high_risk_omitted = [item for item in omitted_relevant_files if item.risk == "high"]
    excluded_receipts = [receipt for receipt in pack.receipts if receipt.action == "excluded"]
    stale = pack.stale or bool(pack.freshness_warnings)
    budget_pressure = pack.budget > 0 and pack.token_estimate >= int(pack.budget * 0.95)
    omitted_reason_counts = Counter(_omitted_reason_bucket(_omitted_reason(item)) for item in omitted_relevant_files)
    excluded_reason_counts = Counter(_excluded_reason_bucket(receipt.reason) for receipt in excluded_receipts)
    freshness_warnings = list(pack.freshness_warnings)

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

    verifier_hint = _verifier_hint(action)
    return {
        "schema_version": 2,
        "recommended_action": action,
        "reason": reason,
        "before_editing": {
            "recommended_action": action,
            "verifier_hint": verifier_hint,
        },
        "task": pack.task,
        "task_hash": pack.freshness.get("packed_task_hash") or pack.freshness.get("task_hash") or "",
        "context_path": pack.freshness.get("context_path", ""),
        "repo_ref": {
            "branch": pack.freshness.get("git_branch", ""),
            "sha": pack.freshness.get("git_sha", ""),
        },
        "pack_snapshot": {
            "generated_at": pack.freshness.get("generated_at", ""),
            "snapshot_hash": pack.freshness.get("snapshot_root_hash", ""),
        },
        # Backward-compatible aliases for existing consumers.
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
            "files": len(omitted_relevant_files),
            "high_risk": len(high_risk_omitted),
            "top": [item.path for item in high_risk_omitted[:5]],
            "reason_counts": _sorted_counts(omitted_reason_counts),
        },
        "skipped_uncertain": {
            "excluded_files": len(excluded_receipts),
            "excluded_reason_counts": _sorted_counts(excluded_reason_counts),
            "freshness_warnings": freshness_warnings,
        },
        "freshness": {
            "refresh_required": stale,
            "warnings": freshness_warnings,
        },
        "suggested_checks": [verifier_hint] if verifier_hint else [],
    }


def _looks_like_test(path: str) -> bool:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return lower.startswith(("tests/", "test/")) or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))


def _omitted_reason(item: OmittedRelevantFile) -> str:
    if item.reasons:
        return item.reasons[0]
    return item.omission_reason


def _sorted_counts(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _omitted_reason_bucket(reason: str) -> str:
    lower = reason.lower()
    if lower.startswith(("related test", "test for")) or "has related tests" in lower:
        return "related_test"
    if lower.startswith(("caller of selected symbol", "reverse dependency")):
        return "caller_or_reverse_dependency"
    if lower.startswith(("direct dependency", "direct content evidence")):
        return "direct_evidence"
    if lower.startswith(("keyword phrase match:", "literal definition match:", "quoted literal match:")):
        return "literal_or_phrase_match"
    if lower.startswith(("matched call:", "matched define:", "matched entrypoint:")):
        return "symbol_or_entrypoint_match"
    if lower.startswith(("matched env read:", "matched external system:", "matched side effect:")):
        return "side_effect_or_external_match"
    if lower.startswith("multi-term path match"):
        return "multi_term_path_match"
    if lower.startswith("api route owner match"):
        return "api_route_owner_match"
    if lower.startswith(("matched domain:", "matched naming keyword:", "matched ranking keyword:", "matched role keyword:")):
        return "broad_keyword_match"
    if lower.startswith(("workspace match", "release/version metadata", "build/dependency metadata")):
        return "repo_metadata_match"
    if lower.startswith("budget"):
        return "budget"
    return reason


def _excluded_reason_bucket(reason: str) -> str:
    lower = reason.lower()
    if lower.startswith("marginal slot replaced by"):
        return "marginal_slot_replaced"
    return _omitted_reason_bucket(reason)


def _verifier_hint(action: NextAction) -> str:
    if action == "refresh_context":
        return "run `agentpack pack` before editing"
    if action == "inspect_omitted_first":
        return "inspect high-risk omitted files before editing shared behavior"
    if action == "deepen_pack":
        return "increase the budget or rerun a deeper pack before broad edits"
    if action == "run_direct_search":
        return "run direct search because no files were selected"
    return "inspect selected files before editing"
