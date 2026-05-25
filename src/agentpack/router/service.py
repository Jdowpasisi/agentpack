from __future__ import annotations

import fnmatch
from pathlib import Path

from agentpack.application.pack_service import PackPlanner, PackRequest
from agentpack.core.config import load_config
from agentpack.router.discovery import discover_inventory, inventory_for_route
from agentpack.router.models import (
    AppliedRule,
    CommandSuggestion,
    RouteExplanation,
    RouteResult,
    SkillInventory,
)
from agentpack.router.prompt_builder import build_agent_prompt
from agentpack.router.scoring import score_skills

_TEST_TERMS = ("test", "tests", "pytest", "flaky", "fixture", "mock", "failing", "fail", "debug")


class RouteService:
    def inventory(self, root: Path, *, use_index: bool = True) -> SkillInventory:
        cfg = load_config(root)
        paths = cfg.skills.paths
        if use_index:
            return inventory_for_route(root, paths)
        return discover_inventory(root, paths)

    def route_task(self, root: Path, task: str) -> RouteResult:
        task = _normalize_task(task)
        cfg = load_config(root)
        plan = PackPlanner().plan(PackRequest(
            root=root,
            agent="generic",
            task=task,
            mode="balanced",
            budget=0,
            since=None,
            refresh=False,
            task_source="route",
        ))
        selected_files = [_selected_file_dict(item) for item in plan.selected[:20]]
        selected_paths = [item["path"] for item in selected_files]

        inventory = self.inventory(root)
        selected_skills, safety_warnings, _all_scores = score_skills(
            inventory.skills,
            task=task,
            selected_paths=selected_paths,
            max_selected=cfg.skills.max_selected,
            allow_external=cfg.skills.allow_external_side_effects,
        )
        applied_rules = _apply_rules(inventory, selected_paths)
        commands = _suggest_commands(task, selected_paths)

        result = RouteResult(
            task=task,
            selected_files=selected_files,
            selected_skills=selected_skills,
            applied_rules=applied_rules,
            suggested_commands=commands,
            safety_warnings=safety_warnings,
        )
        result.agent_prompt = build_agent_prompt(result)
        return result

    def explain_route(self, root: Path, task: str) -> RouteExplanation:
        task = _normalize_task(task)
        result = self.route_task(root, task)
        cfg = load_config(root)
        selected_paths = [item["path"] for item in result.selected_files]
        inventory = self.inventory(root)
        _selected, _warnings, all_scores = score_skills(
            inventory.skills,
            task=task,
            selected_paths=selected_paths,
            max_selected=max(len(inventory.skills), cfg.skills.max_selected),
            allow_external=True,
        )
        return RouteExplanation(**result.model_dump(), skill_scores=all_scores)


def _normalize_task(task: str) -> str:
    normalized = " ".join(task.strip().split())
    if not normalized:
        raise ValueError("Task is required.")
    return normalized


def _selected_file_dict(item) -> dict:
    return {
        "path": item.path,
        "score": item.score,
        "include_mode": item.include_mode,
        "reasons": item.reasons,
    }


def _apply_rules(inventory: SkillInventory, selected_paths: list[str]) -> list[AppliedRule]:
    applied: list[AppliedRule] = []
    for rule in sorted(inventory.rules, key=lambda item: (-item.priority, item.path)):
        reasons = _rule_reasons(rule.scope_paths, selected_paths)
        if reasons:
            applied.append(AppliedRule(rule=rule, reasons=reasons))
    return applied


def _rule_reasons(scope_paths: list[str], selected_paths: list[str]) -> list[str]:
    if not scope_paths:
        return ["repo-level rule"]
    if any(pattern in {"*", "**", "**/*"} for pattern in scope_paths):
        return ["always apply rule"]
    matched = [
        pattern for pattern in scope_paths
        if any(_path_matches(path, pattern) for path in selected_paths)
    ]
    return [f"matched scope: {', '.join(matched[:3])}"] if matched else []


def _suggest_commands(task: str, selected_paths: list[str]) -> list[CommandSuggestion]:
    lower = task.lower()
    test_paths = [
        path for path in selected_paths
        if path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py") or path.endswith("_spec.py")
    ]
    has_test_intent = any(term in lower for term in _TEST_TERMS)
    if not has_test_intent and not test_paths:
        return []

    target = " ".join(test_paths[:3]) if test_paths else ""
    pytest_target = f" {target}" if target else ""
    commands = [
        CommandSuggestion(
            command=f"pytest{pytest_target} -q",
            reason="task or selected files indicate test work",
            source="agentpack-router",
        )
    ]
    if any(term in lower for term in ("flaky", "debug", "fail", "failing")):
        commands.append(CommandSuggestion(
            command=f"pytest{pytest_target} --maxfail=1 -vv",
            reason="task indicates failing/flaky test debugging",
            source="agentpack-router",
        ))
    return commands


def _path_matches(path: str, pattern: str) -> bool:
    normalized_path = path.strip("/")
    normalized_pattern = pattern.strip("/")
    return (
        fnmatch.fnmatch(normalized_path, normalized_pattern)
        or fnmatch.fnmatch(normalized_path, f"{normalized_pattern}/**")
        or normalized_path.startswith(normalized_pattern.rstrip("/") + "/")
    )
