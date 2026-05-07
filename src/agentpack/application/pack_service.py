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
from agentpack.core.context_pack import select_files, save_pack_metadata
from agentpack.core.models import ContextPack, DependencyGraph, FileInfo, ScanResult, SelectedFile, Receipt
from agentpack.core.token_estimator import estimate_tokens
from agentpack.analysis.ranking import score_files, extract_keywords, enrich_keywords_from_files
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
    summary_provider: str


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
    current_snap: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankResult:
    """Result of keyword extraction and file scoring."""
    keywords: set[str]
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
        snap_diff = diff_snapshots(previous_snap, current_snap)
        changed_from_snap: set[str] = set(snap_diff.added + snap_diff.modified)

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

        return ChangeSet(
            all_changed=changed_from_snap | git_changed,
            git_staged=git_staged,
            recently_modified=recently_modified,
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
    ) -> RankResult:
        keywords = extract_keywords(task)
        keywords = enrich_keywords_from_files(keywords, changes.all_changed, packable)
        all_paths = {f.path for f in packable}

        for fi in packable:
            tests = find_related_tests(fi.path, all_paths)
            dep_graph.nodes[fi.path].tests = tests

        scored = score_files(
            packable,
            changed_paths=changes.all_changed,
            staged_paths=changes.git_staged,
            recently_modified=changes.recently_modified,
            dep_graph=dep_graph,
            keywords=keywords,
            include_tests=cfg.context.include_tests,
            include_configs=cfg.context.include_configs,
            weights=cfg.scoring,
        )
        return RankResult(keywords=keywords, scored=scored)


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
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens, previous_snapshot=previous_snap)
        phase_times["scan"] = time.perf_counter() - t0

        packable = scan_result.packable

        t0 = time.perf_counter()
        summaries_objs = build_all_summaries(packable, root, request.summary_provider)
        summaries = {p: s.model_dump() for p, s in summaries_objs.items()}
        phase_times["summarize"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        dep_graph = dep_graph_mod.build(packable, root, summaries=summaries)
        phase_times["deps"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        changes = ChangeDetector().detect(packable, root, request.since, previous_snap=previous_snap)
        phase_times["changes"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        rank_result = FileRanker().rank(packable, changes, dep_graph, request.task, cfg)
        phase_times["rank"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        selected, receipts = select_files(
            files=packable,
            scored=rank_result.scored,
            changed_paths=changes.all_changed,
            summaries=summaries,
            mode=request.mode,  # type: ignore[arg-type]
            budget=effective_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=rank_result.keywords,
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
            scored=rank_result.scored,
            selected=selected,
            receipts=receipts,
            phase_times=phase_times,
            current_snap=changes.current_snap,
        )


class AdapterRegistry:
    """Maps agent names to adapter instances; extensible without touching PackService."""

    @staticmethod
    def get(agent: str, cfg: Any) -> Any:
        from agentpack.adapters.claude import ClaudeAdapter
        from agentpack.adapters.codex import CodexAdapter
        from agentpack.adapters.cursor import CursorAdapter
        from agentpack.adapters.windsurf import WindsurfAdapter
        from agentpack.adapters.generic import GenericAdapter

        adapters = {
            "claude": lambda: ClaudeAdapter(cfg.agents.claude.output),
            "cursor": lambda: CursorAdapter(cfg.agents.generic.output),
            "windsurf": lambda: WindsurfAdapter(cfg.agents.generic.output),
            "codex": lambda: CodexAdapter(cfg.agents.generic.output),
        }
        return adapters.get(agent, lambda: GenericAdapter(cfg.agents.generic.output))()


class PackService:
    """Materializes a plan from PackPlanner into a written context file."""

    def run(self, request: PackRequest) -> PackResult:
        root = request.root
        cfg = load_config(root)

        plan = PackPlanner().plan(request)

        packable = plan.scan_result.packable
        all_tokens = sum(f.estimated_tokens for f in plan.scan_result.all_files)
        raw_tokens = sum(f.estimated_tokens for f in packable)
        packed_tokens = sum(_sf_tokens(sf) for sf in plan.selected)
        saving_pct = (1 - packed_tokens / all_tokens) * 100 if all_tokens > 0 else 0.0

        all_redaction_warnings = [w for sf in plan.selected for w in sf.redaction_warnings]

        pack_obj = ContextPack(
            task=request.task,
            agent=request.agent,
            mode=request.mode,  # type: ignore[arg-type]
            budget=plan.budget,
            token_estimate=packed_tokens,
            raw_repo_tokens=all_tokens,
            after_ignore_tokens=raw_tokens,
            estimated_savings_percent=saving_pct,
            changed_files=sorted(plan.all_changed),
            selected_files=plan.selected,
            receipts=plan.receipts if cfg.context.include_receipts else [],
            redaction_warnings=all_redaction_warnings,
            stale=False,
        )

        adapter = AdapterRegistry.get(request.agent, cfg)

        t0 = time.perf_counter()
        out_path = adapter.write(pack_obj, root)
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
        )
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
) -> None:
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "mode": mode,
        "packed_tokens": packed_tokens,
        "raw_tokens": raw_tokens,
        "saving_pct": round(saving_pct, 1),
        "selected_files": selected_count,
        "changed_files": changed_count,
        "phases": {k: round(v, 3) for k, v in phase_times.items()},
        "total_s": round(sum(phase_times.values()), 3),
    }
    try:
        with metrics_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
