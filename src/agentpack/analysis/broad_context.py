from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from agentpack.core.citations import file_citation
from agentpack.core.models import BroadContext, Citation, FileInfo, ModuleSummary
from agentpack.core.token_estimator import estimate_tokens

_CONFIG_NAMES = {
    "pyproject.toml", "package.json", "pnpm-workspace.yaml", "yarn.lock", "package-lock.json",
    "requirements.txt", "poetry.lock", "setup.py", "setup.cfg", "tox.ini", "ruff.toml",
    "tsconfig.json", "vite.config.ts", "next.config.js", "dockerfile", "docker-compose.yml",
}
_ENTRYPOINT_PARTS = ("main", "app", "cli", "server", "index", "routes", "router", "api")
_TEST_PARTS = ("test", "tests", "spec", "specs")
_DOC_EXTS = {".md", ".rst", ".txt"}


def build_broad_context(
    *,
    files: list[FileInfo],
    summaries: dict[str, Any],
    scored: list[tuple[Any, float, list[str]]],
    intent: str,
    max_module_summaries: int,
    max_inventory_files: int,
    budget_tokens: int,
) -> BroadContext:
    """Build curated broad repo context without extra file reads."""
    if budget_tokens <= 0:
        budget_tokens = 1_000
    score_map = {fi.path: score for fi, score, _reasons in scored}
    packable = sorted(
        (fi for fi in files if not fi.ignored and not fi.binary),
        key=lambda fi: (-score_map.get(fi.path, 0.0), fi.path),
    )
    entrypoints: list[str] = []
    configs: list[str] = []
    docs: list[str] = []
    tests: list[str] = []
    inventory: list[str] = []
    omitted: list[str] = []

    modules: dict[str, list[FileInfo]] = defaultdict(list)
    for fi in packable:
        module = _module_for(fi.path)
        modules[module].append(fi)
        category = _category(fi.path)
        if category == "entrypoint" and len(entrypoints) < 25:
            entrypoints.append(fi.path)
        elif category == "config" and len(configs) < 25:
            configs.append(fi.path)
        elif category == "doc" and len(docs) < 25:
            docs.append(fi.path)
        elif category == "test" and len(tests) < 25:
            tests.append(fi.path)
        if len(inventory) < max_inventory_files:
            inventory.append(fi.path)
        else:
            omitted.append(fi.path)

    ranked_modules = sorted(
        modules.items(),
        key=lambda item: (-_module_score(item[1], score_map), item[0]),
    )
    module_summaries: list[ModuleSummary] = []
    for module, module_files in ranked_modules[:max_module_summaries]:
        module_summaries.append(_summarize_module(module, module_files, summaries, score_map))
    for module, module_files in ranked_modules[max_module_summaries:]:
        omitted.extend(fi.path for fi in module_files[:3])

    context = BroadContext(
        intent=intent,
        inventory_files=len(packable),
        module_summaries=module_summaries,
        entrypoints=_dedupe(entrypoints),
        configs=_dedupe(configs),
        docs=_dedupe(docs),
        tests=_dedupe(tests),
        inventory=_dedupe(inventory),
        semantic_clusters=_semantic_clusters(packable, summaries, score_map),
        omitted_by_budget=_dedupe(omitted),
        citations=_inventory_citations(packable, inventory),
    )
    return _trim_to_budget(context, budget_tokens)


def _module_for(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return "."
    if parts[0] in {"src", "tests", "docs"} and len(parts) > 1:
        return "/".join(parts[:2])
    if parts[0] in {"apps", "packages", "services", "libs"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _category(path: str) -> str:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    suffix = PurePosixPath(lower).suffix
    parts = set(PurePosixPath(lower).parts)
    stem = PurePosixPath(lower).stem
    if name in _CONFIG_NAMES or "config" in stem:
        return "config"
    if suffix in _DOC_EXTS:
        return "doc"
    if parts & set(_TEST_PARTS) or stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test"):
        return "test"
    if any(part in stem for part in _ENTRYPOINT_PARTS):
        return "entrypoint"
    return "file"


def _module_score(files: list[FileInfo], score_map: dict[str, float]) -> float:
    return sum(score_map.get(fi.path, 0.0) for fi in files[:20]) + min(len(files), 20)


def _summarize_module(
    module: str,
    files: list[FileInfo],
    summaries: dict[str, Any],
    score_map: dict[str, float],
) -> ModuleSummary:
    ordered = sorted(files, key=lambda fi: (-score_map.get(fi.path, 0.0), fi.path))
    languages = sorted({fi.language for fi in files if fi.language})[:6]
    key_files = [fi.path for fi in ordered[:8]]
    roles: list[str] = []
    for fi in ordered[:12]:
        summary = summaries.get(fi.path) or {}
        role = summary.get("role") or summary.get("domain") or summary.get("summary")
        if isinstance(role, str) and role.strip():
            roles.append(role.strip().splitlines()[0][:120])
    text = "; ".join(_dedupe(roles)[:3])
    return ModuleSummary(
        path=module,
        files=len(files),
        tokens=sum(fi.estimated_tokens for fi in files),
        languages=languages,
        key_files=key_files,
        summary=text or "Repository area with no cached semantic summary yet.",
        citations=[
            file_citation(
                fi,
                kind="summary",
                claim_id=f"module:{module}:{fi.path}",
                note=f"module summary source for {module}",
            )
            for fi in ordered[:5]
        ],
    )


def _semantic_clusters(
    files: list[FileInfo],
    summaries: dict[str, Any],
    score_map: dict[str, float],
    limit: int = 12,
) -> list[str]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for fi in sorted(files, key=lambda item: (-score_map.get(item.path, 0.0), item.path)):
        summary = summaries.get(fi.path) or {}
        label = summary.get("role") or summary.get("domain")
        if not isinstance(label, str) or not label.strip():
            continue
        key = label.strip().splitlines()[0][:60]
        if len(buckets[key]) < 6:
            buckets[key].append(fi.path)
    ranked = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]
    return [f"{label}: " + ", ".join(paths) for label, paths in ranked]


def _trim_to_budget(context: BroadContext, budget_tokens: int) -> BroadContext:
    while estimate_tokens(context.model_dump_json()) > budget_tokens and context.module_summaries:
        context.omitted_by_budget.extend(context.module_summaries.pop().key_files[:3])
    while estimate_tokens(context.model_dump_json()) > budget_tokens and context.inventory:
        context.omitted_by_budget.append(context.inventory.pop())
    while estimate_tokens(context.model_dump_json()) > budget_tokens and context.semantic_clusters:
        context.semantic_clusters.pop()
    if len(context.omitted_by_budget) > 100:
        context.omitted_by_budget = context.omitted_by_budget[:100]
    return context


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _inventory_citations(files: list[FileInfo], inventory: list[str]) -> list[Citation]:
    by_path = {fi.path: fi for fi in files}
    citations: list[Citation] = []
    for path in inventory[:25]:
        fi = by_path.get(path)
        if fi is None:
            continue
        citations.append(
            file_citation(
                fi,
                kind="summary",
                claim_id=f"broad-context:{path}",
                note="broad context inventory source",
            )
        )
    return citations
