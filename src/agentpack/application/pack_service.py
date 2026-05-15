from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, save_snapshot, load_snapshot
from agentpack.core.diff import diff_snapshots
from agentpack.core import git
from agentpack.core.context_pack import select_files, save_pack_metadata, load_pack_metadata
from agentpack.core.models import ContextPack, DependencyGraph, FileInfo, ScanResult, SelectedFile, Receipt
from agentpack.core.token_estimator import estimate_tokens
from agentpack.renderers.markdown import render_generic
from agentpack.analysis.ranking import (
    score_files,
    extract_keyword_weights,
    enrich_keyword_weights_from_files,
    boost_paired_tests,
    boost_cross_layer_related,
    boost_monorepo_workspaces,
    boost_recall_neighbors,
    boost_second_pass_expansion,
    generic_task_term_ratio,
)
from agentpack.analysis.repo_map import build_repo_map
from agentpack.analysis.monorepo import (
    detect_workspace_dependency_edges,
    detect_workspace_roots,
    normalize_workspace,
)
from agentpack.analysis.task_classifier import classify_task
from agentpack.analysis.tests import find_related_tests
from agentpack.analysis import dependency_graph as dep_graph_mod
from agentpack.summaries.base import build_all_summaries


@dataclass
class PackRequest:
    root: Path
    agent: str
    task: str
    mode: str
    budget: int
    since: str | None
    refresh: bool
    task_source: str = "explicit"
    workspace: str | None = None


@dataclass
class PackResult:
    pack: ContextPack
    out_path: Path
    phase_times: dict[str, float]
    packed_tokens: int
    raw_tokens: int
    saving_pct: float
    changed_files: list[str]
    scan_result: ScanResult


@dataclass
class ChangeSet:
    """Result of change detection: snapshot diff combined with git diff."""
    all_changed: set[str]
    git_staged: set[str]
    recently_modified: list[str]
    source: str
    current_snap: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankResult:
    """Result of keyword extraction and file scoring."""
    keywords: set[str]
    generic_ratio: float
    task_class: str
    task_class_confidence: float
    task_class_signals: list[str]
    scored: list[tuple[Any, float, list[str]]]


@dataclass
class PackPlan:
    """Shared planning output used by both pack and explain."""
    task: str
    mode: str
    budget: int
    scan_result: ScanResult
    summaries: dict[str, Any]
    dep_graph: DependencyGraph
    all_changed: set[str]
    git_staged: set[str]
    recently_modified: list[str]
    keywords: set[str]
    generic_task_ratio: float
    task_class: str
    task_class_confidence: float
    task_class_signals: list[str]
    changed_files_source: str
    repo_map: str
    workspace_roots: list[str]
    workspace_dependency_edges: dict[str, set[str]]
    workspace: str | None
    scored: list[tuple[Any, float, list[str]]]
    selected: list[SelectedFile]
    receipts: list[Receipt]
    phase_times: dict[str, float]
    current_snap: dict[str, Any] = field(default_factory=dict)


class ChangeDetector:
    """Combines snapshot diff + git diff → ChangeSet of changed paths."""

    def detect(
        self,
        packable: list[FileInfo],
        root: Path,
        since: str | None,
        previous_snap: dict | None = None,
    ) -> ChangeSet:
        current_snap = build_snapshot(packable)
        if previous_snap is None:
            previous_snap = load_snapshot(root)
        if previous_snap is None:
            changed_from_snap: set[str] = set()
        else:
            snap_diff = diff_snapshots(previous_snap, current_snap)
            changed_from_snap = set(snap_diff.added + snap_diff.modified)

        git_changed: set[str] = set()
        git_staged: set[str] = set()
        recently_modified: list[str] = []

        if git.is_git_repo(root):
            if since:
                git_changed = git.changed_files_since(root, since)
            else:
                git_changed = git.changed_files(root)
            git_staged = git_changed
            recently_modified = git.recently_modified_files(root)
        packable_paths = {fi.path for fi in packable}
        all_changed = (changed_from_snap | git_changed) & packable_paths
        git_staged = git_staged & packable_paths
        recently_modified = [path for path in recently_modified if path in packable_paths]

        return ChangeSet(
            all_changed=all_changed,
            git_staged=git_staged,
            recently_modified=recently_modified,
            source=_change_source(root, since, changed_from_snap & packable_paths, git_changed & packable_paths),
            current_snap=current_snap,
        )


class FileRanker:
    """Extracts keywords from the task and scores files against them."""

    def rank(
        self,
        packable: list[FileInfo],
        changes: ChangeSet,
        dep_graph: DependencyGraph,
        task: str,
        cfg: Any,
        summaries: dict | None = None,
        root: Path | None = None,
        workspace_roots: list[str] | None = None,
        workspace_dependency_edges: dict[str, set[str]] | None = None,
    ) -> RankResult:
        from agentpack.core import git as _git
        keyword_weights = extract_keyword_weights(task)
        keyword_weights = enrich_keyword_weights_from_files(keyword_weights, changes.all_changed, packable)
        keywords = set(keyword_weights)
        generic_ratio = generic_task_term_ratio(task)
        task_classification = classify_task(task)
        all_paths = {f.path for f in packable}

        for fi in packable:
            tests = find_related_tests(fi.path, all_paths)
            dep_graph.nodes[fi.path].tests = tests

        churn_counts: dict[str, int] = {}
        co_changed_paths: dict[str, int] = {}
        if root is not None and _git.is_git_repo(root):
            churn_counts = _git.file_churn_counts(root)
            co_changed_paths = _filter_co_changed_paths(
                root,
                _git.co_changed_files(root, changes.all_changed),
            )

        scored = score_files(
            packable,
            changed_paths=changes.all_changed,
            staged_paths=changes.git_staged,
            recently_modified=changes.recently_modified,
            dep_graph=dep_graph,
            keywords=keyword_weights,
            include_tests=cfg.context.include_tests,
            include_configs=cfg.context.include_configs,
            weights=cfg.scoring,
            summaries=summaries,
            churn_counts=churn_counts,
            co_changed_paths=co_changed_paths,
        )
        scored = boost_monorepo_workspaces(
            scored,
            workspace_roots=workspace_roots or [],
            workspace_dependency_edges=workspace_dependency_edges or {},
            changed_paths=changes.all_changed,
            task=task,
            weights=cfg.scoring,
        )
        scored = boost_recall_neighbors(scored, dep_graph, changes.all_changed, weights=cfg.scoring)
        scored = boost_second_pass_expansion(scored, dep_graph, keyword_weights, weights=cfg.scoring)
        scored = boost_cross_layer_related(scored, keyword_weights, weights=cfg.scoring)
        scored = boost_paired_tests(scored, weights=cfg.scoring)
        if root is not None:
            scored = _apply_history_penalties(root, scored, changes.all_changed)
        return RankResult(
            keywords=keywords,
            generic_ratio=generic_ratio,
            task_class=task_classification.kind,
            task_class_confidence=task_classification.confidence,
            task_class_signals=task_classification.signals,
            scored=scored,
        )


class PackPlanner:
    """Runs scan → summarize → graph → rank → select; shared by pack and explain."""

    def plan(self, request: PackRequest) -> PackPlan:
        root = request.root
        cfg = load_config(root)
        effective_budget = request.budget if request.budget > 0 else cfg.context.default_budget
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        phase_times: dict[str, float] = {}

        t0 = time.perf_counter()
        previous_snap = load_snapshot(root)
        workspace_roots = detect_workspace_roots(root)
        workspace = _resolve_workspace(root, request.workspace, workspace_roots)
        workspace_dependency_edges = detect_workspace_dependency_edges(root, workspace_roots)
        include_globs = _workspace_include_globs(workspace, cfg.project.include_globs or [])
        scan_result = scan(
            root, ignore_spec, cfg.context.max_file_tokens,
            previous_snapshot=previous_snap,
            include_globs=include_globs or None,
            exclude_globs=cfg.project.exclude_globs or None,
            always_skip_paths=AdapterRegistry.generated_output_paths(root, cfg),
        )
        phase_times["scan"] = time.perf_counter() - t0

        packable = scan_result.packable

        t0 = time.perf_counter()
        summaries_objs = build_all_summaries(packable, root)
        summaries = {p: s.model_dump() for p, s in summaries_objs.items()}
        phase_times["summarize"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        dep_graph = dep_graph_mod.build(packable, root, summaries=summaries)
        phase_times["deps"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        changes = ChangeDetector().detect(packable, root, request.since, previous_snap=previous_snap)
        phase_times["changes"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        rank_result = FileRanker().rank(
            packable,
            changes,
            dep_graph,
            request.task,
            cfg,
            summaries=summaries,
            root=root,
            workspace_roots=workspace_roots,
            workspace_dependency_edges=workspace_dependency_edges,
        )
        if not changes.all_changed:
            rank_result.scored = _apply_no_live_precision_guard(rank_result.scored, rank_result.generic_ratio)
        phase_times["rank"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        repo_map_budget = _repo_map_budget_for_mode(request.mode, effective_budget)
        repo_map = build_repo_map(
            files=packable,
            scored=rank_result.scored,
            summaries=summaries,
            dep_graph=dep_graph,
            changed_paths=changes.all_changed,
            budget_tokens=repo_map_budget,
        )
        phase_times["repo_map"] = time.perf_counter() - t0
        selection_budget = max(0, effective_budget - estimate_tokens(repo_map))

        t0 = time.perf_counter()
        selected, receipts = select_files(
            files=packable,
            scored=rank_result.scored,
            changed_paths=changes.all_changed,
            summaries=summaries,
            mode=request.mode,  # type: ignore[arg-type]
            budget=selection_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=rank_result.keywords,
            min_summary_score=_guarded_summary_score_floor(
                root, cfg, request.mode, rank_result.generic_ratio, no_live_changes=not changes.all_changed
            ),
            max_summary_files=_guarded_summary_cap(
                root,
                cfg,
                request.mode,
                rank_result.generic_ratio,
                no_live_changes=not changes.all_changed,
                effective_budget=effective_budget,
            ),
        )
        phase_times["select"] = time.perf_counter() - t0

        return PackPlan(
            task=request.task,
            mode=request.mode,
            budget=effective_budget,
            scan_result=scan_result,
            summaries=summaries,
            dep_graph=dep_graph,
            all_changed=changes.all_changed,
            git_staged=changes.git_staged,
            recently_modified=changes.recently_modified,
            keywords=rank_result.keywords,
            generic_task_ratio=rank_result.generic_ratio,
            task_class=rank_result.task_class,
            task_class_confidence=rank_result.task_class_confidence,
            task_class_signals=rank_result.task_class_signals,
            changed_files_source=changes.source,
            repo_map=repo_map,
            workspace_roots=workspace_roots,
            workspace_dependency_edges=workspace_dependency_edges,
            workspace=workspace,
            scored=rank_result.scored,
            selected=selected,
            receipts=receipts,
            phase_times=phase_times,
            current_snap=changes.current_snap,
        )


class AdapterRegistry:
    """Maps agent names to adapter instances; extensible without touching PackService."""

    @staticmethod
    def _factories(cfg: Any) -> dict[str, Any]:
        from agentpack.adapters.antigravity import AntigravityAdapter
        from agentpack.adapters.claude import ClaudeAdapter
        from agentpack.adapters.codex import CodexAdapter
        from agentpack.adapters.cursor import CursorAdapter
        from agentpack.adapters.windsurf import WindsurfAdapter
        from agentpack.adapters.generic import GenericAdapter

        return {
            "antigravity": lambda: AntigravityAdapter(),
            "claude": lambda: ClaudeAdapter(cfg.agents.claude.output),
            "cursor": lambda: CursorAdapter(cfg.agents.generic.output),
            "windsurf": lambda: WindsurfAdapter(cfg.agents.generic.output),
            "codex": lambda: CodexAdapter(cfg.agents.generic.output),
            "generic": lambda: GenericAdapter(cfg.agents.generic.output),
        }

    @staticmethod
    def get(agent: str, cfg: Any) -> Any:
        from agentpack.adapters.generic import GenericAdapter

        adapters = AdapterRegistry._factories(cfg)
        return adapters.get(agent, lambda: GenericAdapter(cfg.agents.generic.output))()

    @staticmethod
    def generated_output_paths(root: Path, cfg: Any) -> set[str]:
        paths: set[str] = set()
        for factory in AdapterRegistry._factories(cfg).values():
            try:
                out_path = factory().output_path(root)
                paths.add(str(out_path.relative_to(root)).replace("\\", "/"))
            except (OSError, ValueError):
                continue
        return paths


class PackService:
    """Materializes a plan from PackPlanner into a written context file."""

    def run(self, request: PackRequest) -> PackResult:
        root = request.root
        cfg = load_config(root)

        plan = PackPlanner().plan(request)

        packable = plan.scan_result.packable
        all_tokens = sum(f.estimated_tokens for f in plan.scan_result.all_files)
        raw_tokens = sum(f.estimated_tokens for f in packable)
        previous_metadata = load_pack_metadata(root)
        delta_summary = _compute_delta_summary(previous_metadata, plan.selected, plan.all_changed)
        packed_tokens = (
            sum(_sf_tokens(sf) for sf in plan.selected)
            + estimate_tokens(plan.repo_map)
            + estimate_tokens(delta_summary)
        )
        saving_pct = max(0.0, (1 - packed_tokens / all_tokens) * 100) if all_tokens > 0 else 0.0

        all_redaction_warnings = [w for sf in plan.selected for w in sf.redaction_warnings]
        freshness = _build_freshness_metadata(
            root,
            request=request,
            plan=plan,
            snapshot_root_hash=plan.current_snap["root_hash"],
        )
        if delta_summary:
            freshness["delta_summary"] = delta_summary
        freshness_warnings = _freshness_warnings(root, request, freshness)

        pack_obj = ContextPack(
            task=request.task,
            agent=request.agent,
            mode=request.mode,  # type: ignore[arg-type]
            task_class=plan.task_class,
            budget=plan.budget,
            token_estimate=packed_tokens,
            raw_repo_tokens=all_tokens,
            after_ignore_tokens=raw_tokens,
            estimated_savings_percent=saving_pct,
            repo_map=plan.repo_map,
            delta_summary=delta_summary,
            changed_files=sorted(plan.all_changed),
            selected_files=plan.selected,
            receipts=plan.receipts if cfg.context.include_receipts else [],
            redaction_warnings=all_redaction_warnings,
            stale=False,
            freshness=freshness,
            freshness_warnings=freshness_warnings,
        )

        adapter = AdapterRegistry.get(request.agent, cfg)

        t0 = time.perf_counter()
        out_path = adapter.write(pack_obj, root)
        _write_canonical_context(pack_obj, root, out_path)
        if plan.workspace:
            out_path = _write_workspace_context(pack_obj, root, plan.workspace)
        plan.phase_times["render"] = time.perf_counter() - t0

        save_snapshot(plan.current_snap, root)
        save_pack_metadata(
            root,
            context_path=str(out_path.relative_to(root)),
            snapshot_root_hash=plan.current_snap["root_hash"],
            task=request.task,
            agent=request.agent,
            mode=request.mode,
            budget=plan.budget,
            token_estimate=packed_tokens,
            freshness=freshness,
            freshness_warnings=freshness_warnings,
            selected_files=_selected_file_metadata(plan.selected),
        )
        excluded_receipts = [r for r in plan.receipts if r.action == "excluded"]
        # Budget-cut: files that scored OK but didn't fit — more useful signal than "score too low"
        budget_cut = [r.path for r in plan.receipts if r.reason == "budget exhausted"][:10]
        _record_metrics(
            root,
            task=request.task,
            mode=request.mode,
            phase_times=plan.phase_times,
            packed_tokens=packed_tokens,
            raw_tokens=all_tokens,
            saving_pct=saving_pct,
            selected_count=len(plan.selected),
            changed_count=len(plan.all_changed),
            selected_paths=[sf.path for sf in plan.selected],
            selected_tokens={sf.path: _sf_tokens(sf) for sf in plan.selected},
            selected_modes={sf.path: sf.include_mode for sf in plan.selected},
            selected_hints=[{"path": sf.path, "why": sf.reasons[0] if sf.reasons else ""} for sf in plan.selected[:8]],
            current_changed=plan.all_changed,
            task_class=plan.task_class,
            workspace=plan.workspace,
            workspace_roots=plan.workspace_roots,
            excluded_count=len(excluded_receipts),
            excluded_paths=budget_cut,
        )

        return PackResult(
            pack=pack_obj,
            out_path=out_path,
            phase_times=plan.phase_times,
            packed_tokens=packed_tokens,
            raw_tokens=all_tokens,
            saving_pct=saving_pct,
            changed_files=sorted(plan.all_changed),
            scan_result=plan.scan_result,
        )


def _write_canonical_context(pack: ContextPack, root: Path, out_path: Path) -> None:
    """Keep .agentpack/context.md fresh even when the target agent writes elsewhere."""
    canonical_path = root / ".agentpack" / "context.md"
    try:
        if out_path.resolve() == canonical_path.resolve():
            return
    except OSError:
        if out_path == canonical_path:
            return
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(render_generic(pack), encoding="utf-8")


def _write_workspace_context(pack: ContextPack, root: Path, workspace: str) -> Path:
    safe = workspace.replace("/", "__").replace("\\", "__")
    workspace_path = root / ".agentpack" / "workspaces" / safe / "context.md"
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_path.write_text(render_generic(pack), encoding="utf-8")
    return workspace_path


def _resolve_workspace(root: Path, workspace: str | None, workspace_roots: list[str]) -> str | None:
    value = normalize_workspace(workspace)
    if value is None:
        return None
    if value in workspace_roots or (root / value).is_dir():
        return value
    known = ", ".join(workspace_roots[:8]) if workspace_roots else "none detected"
    raise ValueError(f"Unknown workspace '{value}'. Known workspaces: {known}")


def _workspace_include_globs(workspace: str | None, configured: list[str]) -> list[str]:
    if workspace is None:
        return configured
    return [f"{workspace}/**"]


def _selected_file_metadata(selected: list[SelectedFile]) -> list[dict[str, Any]]:
    return [
        {
            "path": sf.path,
            "mode": sf.include_mode,
            "score": round(sf.score, 1),
            "why": sf.reasons[0] if sf.reasons else "",
            "reasons": sf.reasons,
            "tokens": _sf_tokens(sf),
        }
        for sf in selected
    ]


def _sf_tokens(sf: SelectedFile) -> int:
    if sf.content:
        return estimate_tokens(sf.content)
    parts: list[str] = []
    if sf.summary:
        parts.append(sf.summary)
    for sym in sf.symbols:
        if sym.signature:
            parts.append(sym.signature)
    return estimate_tokens("\n".join(parts)) if parts else 50


def _repo_map_budget_for_mode(mode: str, effective_budget: int) -> int:
    caps = {"minimal": 300, "balanced": 600, "deep": 900}
    return min(caps.get(mode, 500), max(0, effective_budget // 20))


def _apply_history_penalties(
    root: Path,
    scored: list[tuple[Any, float, list[str]]],
    changed_paths: set[str],
    *,
    window: int = 20,
) -> list[tuple[Any, float, list[str]]]:
    """Downrank paths that recent packs proved noisy for later edits."""
    counts = _history_noise_counts(root, window=window)
    if not counts:
        return scored

    adjusted: list[tuple[Any, float, list[str]]] = []
    for fi, score, reasons in scored:
        if fi.path in changed_paths:
            adjusted.append((fi, score, reasons))
            continue
        count = counts.get(fi.path, 0)
        if count <= 0:
            adjusted.append((fi, score, reasons))
            continue
        penalty = min(25.0, count * 4.0)
        adjusted.append((fi, max(0.0, score - penalty), [*reasons, f"history noise penalty -{penalty:.0f}"]))
    return adjusted


def _history_noise_counts(root: Path, *, window: int = 20) -> dict[str, int]:
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if not metrics_path.exists():
        return {}
    counts: dict[str, int] = {}
    try:
        lines = metrics_path.read_text(encoding="utf-8").splitlines()[-window:]
    except OSError:
        return {}
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        for path in rec.get("selection_noise_paths", []) or []:
            if isinstance(path, str):
                counts[path] = counts.get(path, 0) + 1
    return counts


def _filter_co_changed_paths(
    root: Path,
    co_changed_paths: dict[str, int],
    *,
    min_count: int = 2,
    max_noise_count: int = 4,
) -> dict[str, int]:
    """Keep only repeated, not-recently-noisy co-change hints.

    Single co-change commits are often incidental. Repeated noisy files should
    not get revived by the recall boost after metrics already proved them bad.
    """
    if not co_changed_paths:
        return {}
    noise_counts = _history_noise_counts(root)
    return {
        path: count
        for path, count in co_changed_paths.items()
        if count >= min_count and noise_counts.get(path, 0) <= max_noise_count
    }


_NO_LIVE_STRONG_SIGNALS = (
    "symbol keyword match",
    "content keyword match",
    "direct dependency",
    "reverse dependency",
    "has related tests",
    "test for",
    "config file",
    "knowledge/architecture doc",
    "historically co-changed",
)


def _apply_no_live_precision_guard(
    scored: list[tuple[Any, float, list[str]]],
    generic_ratio: float,
) -> list[tuple[Any, float, list[str]]]:
    """Tighten ranking when task keywords are the only signal.

    No-live-change packs are useful as orientation, but they are also where
    filename and summary noise dominate. Keep corroborated files, damp weak
    filename-only hits, and avoid letting broad task words fan out across repo.
    """
    adjusted: list[tuple[Any, float, list[str]]] = []
    broad_task = generic_ratio >= 0.35
    for fi, score, reasons in scored:
        has_filename = any(reason.startswith("filename keyword match") for reason in reasons)
        has_strong = any(reason.startswith(_NO_LIVE_STRONG_SIGNALS) for reason in reasons)
        if has_filename and not has_strong:
            damped = min(score, max(0.0, score * 0.35))
            adjusted.append((fi, damped, [*reasons, "no-live filename-only dampening"]))
            continue
        if broad_task and has_filename and not any(
            reason.startswith(("symbol keyword match", "content keyword match", "historically co-changed"))
            for reason in reasons
        ):
            adjusted.append((fi, max(0.0, score - 30), [*reasons, "broad-task filename dampening"]))
            continue
        adjusted.append((fi, score, reasons))
    return adjusted


def _compute_delta_summary(
    previous_metadata: dict[str, Any] | None,
    selected: list[SelectedFile],
    changed_paths: set[str],
) -> str:
    if not previous_metadata:
        return ""
    previous = previous_metadata.get("selected_files_meta") or []
    if not isinstance(previous, list):
        return ""
    prev_modes = {
        item.get("path"): item.get("mode")
        for item in previous
        if isinstance(item, dict) and item.get("path")
    }
    current_modes = {sf.path: sf.include_mode for sf in selected}
    added = sorted(set(current_modes) - set(prev_modes))
    removed = sorted(set(prev_modes) - set(current_modes))
    mode_changed = sorted(
        path for path, mode in current_modes.items()
        if path in prev_modes and prev_modes[path] != mode
    )
    if not (added or removed or mode_changed or changed_paths):
        return "No selected-file delta since last pack."
    lines = [
        f"Selected delta: +{len(added)} new, -{len(removed)} removed, {len(mode_changed)} mode changed; "
        f"{len(changed_paths)} live changed files."
    ]
    if added:
        lines.append("New: " + ", ".join(added[:6]))
    if removed:
        lines.append("Removed: " + ", ".join(removed[:6]))
    if mode_changed:
        lines.append("Mode changed: " + ", ".join(mode_changed[:6]))
    return "\n".join(lines)


def _summary_score_floor(cfg: Any, generic_ratio: float) -> float:
    floor = cfg.context.min_summary_score
    if generic_ratio >= 0.5:
        return floor + 15
    if generic_ratio >= 0.35:
        return floor + 8
    return floor


def _summary_cap_for_mode(cfg: Any, mode: str, generic_ratio: float = 0.0) -> int:
    if mode == "minimal":
        cap = cfg.context.max_summary_files_minimal
    elif mode == "balanced":
        cap = cfg.context.max_summary_files_balanced
    elif mode == "deep":
        cap = cfg.context.max_summary_files_deep
    else:
        cap = 0
    if cap > 0 and generic_ratio >= 0.5:
        return max(8, cap // 2)
    if cap > 0 and generic_ratio >= 0.35:
        return max(12, int(cap * 0.75))
    return cap


def _guarded_summary_score_floor(
    root: Path,
    cfg: Any,
    mode: str,
    generic_ratio: float,
    *,
    no_live_changes: bool = False,
) -> float:
    floor = _summary_score_floor(cfg, generic_ratio)
    avg_summary_precision, rows = _recent_summary_token_precision(root)
    if rows < 3:
        return floor + (15 if no_live_changes else 0)
    if avg_summary_precision <= 0.05:
        return floor + (140 if no_live_changes else 80)
    if avg_summary_precision <= 0.15:
        return floor + (80 if no_live_changes else 40)
    if no_live_changes:
        return floor + 35
    return floor


def _guarded_summary_cap(
    root: Path,
    cfg: Any,
    mode: str,
    generic_ratio: float = 0.0,
    *,
    no_live_changes: bool = False,
    effective_budget: int = 0,
) -> int:
    cap = _summary_cap_for_mode(cfg, mode, generic_ratio)
    if no_live_changes and effective_budget and effective_budget <= 2500 and cap > 0:
        cap = min(cap, 4 if mode == "minimal" else 6)
    avg_summary_precision, rows = _recent_summary_token_precision(root)
    if rows < 3:
        if no_live_changes and cap > 0:
            if effective_budget and effective_budget <= 2500:
                return min(cap, 4 if mode == "minimal" else 6)
            if effective_budget and effective_budget <= 6000:
                return min(cap, 12 if mode == "minimal" else 16)
            return min(cap, 16)
        return cap
    if avg_summary_precision <= 0.05:
        if no_live_changes:
            return -1
        strict_cap = 3 if mode == "minimal" else 5 if mode == "balanced" else 10
    elif avg_summary_precision <= 0.15:
        strict_cap = 3 if no_live_changes else 6 if mode == "minimal" else 12 if mode == "balanced" else 20
    else:
        if no_live_changes and cap > 0:
            return min(cap, 8)
        return cap
    if cap <= 0:
        return strict_cap
    return min(cap, strict_cap)


def _recent_summary_token_precision(root: Path, window: int = 10) -> tuple[float, int]:
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if not metrics_path.exists():
        return 1.0, 0
    values: list[float] = []
    try:
        lines = metrics_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1.0, 0
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        value = rec.get("selection_token_precision_summary")
        if isinstance(value, int | float):
            values.append(float(value))
            if len(values) >= window:
                break
    if not values:
        return 1.0, 0
    return sum(values) / len(values), len(values)


def _change_source(root: Path, since: str | None, snapshot_changed: set[str], git_changed: set[str]) -> str:
    if not git.is_git_repo(root):
        return "snapshot diff"
    if since:
        return f"git diff since {since} + snapshot diff"
    if git_changed and snapshot_changed:
        return "git working tree + snapshot diff"
    if git_changed:
        return "git working tree"
    if snapshot_changed:
        return "snapshot diff"
    return "no live changes; ranking used task keywords and history"


def _task_md_body(root: Path) -> str | None:
    task_md_path = root / ".agentpack" / "task.md"
    if not task_md_path.exists():
        return None
    try:
        content = task_md_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    lines = [ln for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
    body = lines[0].strip() if lines else ""
    placeholder = "Write or update the current coding task here."
    if body and placeholder not in body:
        return body
    return None


def _build_freshness_metadata(
    root: Path,
    *,
    request: PackRequest,
    plan: PackPlan,
    snapshot_root_hash: str,
) -> dict[str, Any]:
    dirty = git.dirty_files(root) if git.is_git_repo(root) else set()
    metadata: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_source": request.task_source,
        "changed_files_source": plan.changed_files_source,
        "snapshot_root_hash": snapshot_root_hash,
        "generic_task_ratio": round(plan.generic_task_ratio, 3),
        "task_class": plan.task_class,
        "task_class_confidence": plan.task_class_confidence,
        "task_class_signals": plan.task_class_signals,
        "dirty_files_count": len(dirty),
    }
    if plan.workspace:
        metadata["workspace"] = plan.workspace
    if plan.workspace_roots:
        metadata["workspace_roots"] = plan.workspace_roots
    if plan.workspace_dependency_edges:
        metadata["workspace_dependency_edges"] = {
            key: sorted(value) for key, value in plan.workspace_dependency_edges.items() if value
        }
    if git.is_git_repo(root):
        metadata["git_sha"] = git.current_sha(root)
        metadata["git_branch"] = git.current_branch(root)
    if dirty:
        metadata["dirty_files_sample"] = sorted(dirty)[:8]
    task_md = _task_md_body(root)
    if task_md:
        metadata["task_md"] = task_md
    return metadata


def _freshness_warnings(root: Path, request: PackRequest, freshness: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    task_md = freshness.get("task_md")
    if task_md and task_md != request.task:
        warnings.append(
            ".agentpack/task.md differs from the packed task; rerun with --task auto if task.md should win."
        )
    if freshness.get("changed_files_source") == "no live changes; ranking used task keywords and history":
        warnings.append("No live changed files were detected; treat selected files as keyword-based hints.")
    if freshness.get("generic_task_ratio", 0) >= 0.5:
        warnings.append("Task terms are broad/generic; pack tightened weak-summary selection.")
    saved_sha = freshness.get("git_sha")
    current_sha = git.current_sha(root) if git.is_git_repo(root) else None
    if saved_sha and current_sha and saved_sha != current_sha:
        warnings.append("Git HEAD changed since this pack was generated.")
    return warnings


def _load_last_record(metrics_path: Path) -> dict[str, Any] | None:
    """Return the most recent metrics record that has selected_paths."""
    if not metrics_path.exists():
        return None
    try:
        lines = metrics_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("selected_paths"):
                return rec
    except Exception:
        pass
    return None


def _compute_selection_accuracy(
    root: Path,
    metrics_path: Path,
    current_selected: list[str],
    current_changed: set[str],
) -> dict[str, Any]:
    """Compare previous pack's selected_paths vs files actually changed since then.

    recall    = |predicted ∩ actual_changed| / |actual_changed|
    precision = |predicted ∩ actual_changed| / |predicted|
    """
    prev = _load_last_record(metrics_path)
    if prev is None:
        return {}

    prev_selected: set[str] = set(prev["selected_paths"])
    # actual_changed = files changed since the previous pack (current git diff)
    actual_changed: set[str] = current_changed
    if not actual_changed or not prev_selected:
        return {}

    hits = prev_selected & actual_changed
    support = {
        path for path in prev_selected - hits
        if _support_matches_changed(path, actual_changed)
    }
    recall = len(hits) / len(actual_changed)
    precision = len(hits) / len(prev_selected)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    context_precision = (len(hits) + len(support)) / len(prev_selected)
    result = {
        "selection_recall": round(recall, 3),
        "selection_precision": round(precision, 3),
        "selection_f1": round(f1, 3),
        "selection_hit_paths": sorted(hits),
        "selection_support_paths": sorted(support),
        "selection_context_precision": round(context_precision, 3),
        "selection_noise_paths": sorted(prev_selected - hits - support),
    }
    token_map = prev.get("selected_tokens") or {}
    if isinstance(token_map, dict):
        total_tokens = sum(v for v in token_map.values() if isinstance(v, int | float))
        hit_tokens = sum(
            token_map.get(path, 0)
            for path in hits
            if isinstance(token_map.get(path, 0), int | float)
        )
        if total_tokens > 0:
            token_precision = hit_tokens / total_tokens
            support_tokens = sum(
                token_map.get(path, 0)
                for path in support
                if isinstance(token_map.get(path, 0), int | float)
            )
            result["selection_token_precision"] = round(token_precision, 3)
            result["selection_token_context_precision"] = round((hit_tokens + support_tokens) / total_tokens, 3)
            result["selection_noise_pct"] = round((1 - token_precision) * 100, 1)
        mode_map = prev.get("selected_modes") or {}
        if isinstance(mode_map, dict):
            for mode in ("full", "diff", "symbols", "skeleton", "summary"):
                mode_paths = {path for path, value in mode_map.items() if value == mode}
                mode_total = sum(
                    token_map.get(path, 0)
                    for path in mode_paths
                    if isinstance(token_map.get(path, 0), int | float)
                )
                if mode_total <= 0:
                    continue
                mode_hit_tokens = sum(
                    token_map.get(path, 0)
                    for path in mode_paths & hits
                    if isinstance(token_map.get(path, 0), int | float)
                )
                result[f"selection_token_precision_{mode}"] = round(mode_hit_tokens / mode_total, 3)
    return result


def _support_matches_changed(path: str, changed_paths: set[str]) -> bool:
    """Heuristic for read-only support context that was plausibly useful.

    Edit precision only rewards files later changed. This helper gives partial
    credit to obvious support files such as paired tests or files sharing a
    meaningful stem/domain with a changed file.
    """
    from agentpack.analysis.ranking import _is_test_file, _test_matches_source

    p = Path(path)
    path_stem = p.stem.removeprefix("test_").removesuffix("_test")
    path_parts = {part.lower() for part in p.parts if len(part) >= 3}
    for changed in changed_paths:
        c = Path(changed)
        changed_stem = c.stem.removeprefix("test_").removesuffix("_test")
        if _is_test_file(path) and _test_matches_source(path, changed):
            return True
        if _is_test_file(changed) and _test_matches_source(changed, path):
            return True
        if path_stem and path_stem == changed_stem:
            return True
        changed_parts = {part.lower() for part in c.parts if len(part) >= 3}
        shared = (path_parts & changed_parts) - {"src", "app", "test", "tests", "lib", "core"}
        if len(shared) >= 2:
            return True
    return False


def _record_metrics(
    root: Path,
    *,
    task: str,
    mode: str,
    phase_times: dict[str, float],
    packed_tokens: int,
    raw_tokens: int,
    saving_pct: float,
    selected_count: int,
    changed_count: int,
    selected_paths: list[str],
    selected_tokens: dict[str, int],
    selected_modes: dict[str, str],
    current_changed: set[str],
    task_class: str = "general",
    workspace: str | None = None,
    workspace_roots: list[str] | None = None,
    selected_hints: list[dict] | None = None,
    excluded_count: int = 0,
    excluded_paths: list[str] | None = None,
) -> None:
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    accuracy = _compute_selection_accuracy(root, metrics_path, selected_paths, current_changed)
    mode_counts: dict[str, int] = {}
    mode_tokens: dict[str, int] = {}
    for path, include_mode in selected_modes.items():
        mode_counts[include_mode] = mode_counts.get(include_mode, 0) + 1
        mode_tokens[include_mode] = mode_tokens.get(include_mode, 0) + selected_tokens.get(path, 0)
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "task_class": task_class,
        "workspace": workspace,
        "workspace_roots": workspace_roots or [],
        "mode": mode,
        "packed_tokens": packed_tokens,
        "raw_tokens": raw_tokens,
        "saving_pct": round(saving_pct, 1),
        "compression_ratio": round(packed_tokens / raw_tokens, 4) if raw_tokens > 0 else 0,
        "selected_files": selected_count,
        "changed_files": changed_count,
        "current_changed_paths": sorted(current_changed),
        "excluded_files": excluded_count,
        "excluded_paths": excluded_paths or [],
        "selected_paths": selected_paths,
        "selected_tokens": selected_tokens,
        "selected_modes": selected_modes,
        "mode_counts": mode_counts,
        "mode_tokens": mode_tokens,
        "selected_hints": selected_hints or [],
        "phases": {k: round(v, 3) for k, v in phase_times.items()},
        "total_s": round(sum(phase_times.values()), 3),
    }
    record.update(accuracy)
    try:
        with metrics_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
