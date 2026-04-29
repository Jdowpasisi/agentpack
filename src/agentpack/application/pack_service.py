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
from agentpack.core.models import ContextPack, ScanResult, SelectedFile, Receipt
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


class PackService:
    """Orchestrates the full pack pipeline: scan → summarize → graph → rank → select → render → persist."""

    def run(self, request: PackRequest) -> PackResult:
        from agentpack.adapters.claude import ClaudeAdapter
        from agentpack.adapters.codex import CodexAdapter
        from agentpack.adapters.cursor import CursorAdapter
        from agentpack.adapters.windsurf import WindsurfAdapter
        from agentpack.adapters.generic import GenericAdapter

        root = request.root
        cfg = load_config(root)
        effective_budget = request.budget if request.budget > 0 else cfg.context.default_budget
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        phase_times: dict[str, float] = {}

        t0 = time.perf_counter()
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
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
        current_snap = build_snapshot(packable)
        previous_snap = load_snapshot(root)
        snap_diff = diff_snapshots(previous_snap, current_snap)
        changed_from_snap: set[str] = set(snap_diff.added + snap_diff.modified)

        git_changed: set[str] = set()
        git_staged: set[str] = set()
        recently_modified: list[str] = []

        if git.is_git_repo(root):
            if request.since:
                git_changed = git.changed_files_since(root, request.since)
            else:
                git_changed = git.changed_files(root)
            git_staged = git_changed
            recently_modified = git.recently_modified_files(root)

        all_changed = changed_from_snap | git_changed
        phase_times["changes"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        keywords = extract_keywords(request.task)
        keywords = enrich_keywords_from_files(keywords, all_changed, packable)
        all_paths = {f.path for f in packable}

        for fi in packable:
            graph_entry = dep_graph.get(fi.path, {})
            tests = find_related_tests(fi.path, all_paths)
            graph_entry["tests"] = tests
            dep_graph[fi.path] = graph_entry

        scored = score_files(
            packable,
            changed_paths=all_changed,
            staged_paths=git_staged,
            recently_modified=recently_modified,
            dep_graph=dep_graph,
            keywords=keywords,
            include_tests=cfg.context.include_tests,
            include_configs=cfg.context.include_configs,
            weights=cfg.scoring,
        )
        phase_times["rank"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        selected, receipts = select_files(
            files=packable,
            scored=scored,
            changed_paths=all_changed,
            summaries=summaries,
            mode=request.mode,  # type: ignore[arg-type]
            budget=effective_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=keywords,
        )
        phase_times["select"] = time.perf_counter() - t0

        all_tokens = sum(f.estimated_tokens for f in scan_result.all_files)
        raw_tokens = sum(f.estimated_tokens for f in packable)
        packed_tokens = sum(_sf_tokens(sf) for sf in selected)
        saving_pct = (1 - packed_tokens / all_tokens) * 100 if all_tokens > 0 else 0.0
        after_ignore = raw_tokens

        all_redaction_warnings = [w for sf in selected for w in sf.redaction_warnings]

        pack_obj = ContextPack(
            task=request.task,
            agent=request.agent,
            mode=request.mode,  # type: ignore[arg-type]
            budget=effective_budget,
            token_estimate=packed_tokens,
            raw_repo_tokens=all_tokens,
            after_ignore_tokens=after_ignore,
            estimated_savings_percent=saving_pct,
            changed_files=sorted(all_changed),
            selected_files=selected,
            receipts=receipts if cfg.context.include_receipts else [],
            redaction_warnings=all_redaction_warnings,
            stale=False,
        )

        _adapters = {
            "claude": lambda: ClaudeAdapter(cfg.agents.claude.output),
            "cursor": lambda: CursorAdapter(cfg.agents.generic.output),
            "windsurf": lambda: WindsurfAdapter(cfg.agents.generic.output),
            "codex": lambda: CodexAdapter(cfg.agents.generic.output),
        }
        adapter = _adapters.get(request.agent, lambda: GenericAdapter(cfg.agents.generic.output))()

        t0 = time.perf_counter()
        out_path = adapter.write(pack_obj, root)
        phase_times["render"] = time.perf_counter() - t0

        save_snapshot(current_snap, root)
        save_pack_metadata(
            root,
            context_path=str(out_path.relative_to(root)),
            snapshot_root_hash=current_snap["root_hash"],
            task=request.task,
            agent=request.agent,
            mode=request.mode,
            budget=effective_budget,
            token_estimate=packed_tokens,
        )
        _record_metrics(
            root,
            task=request.task,
            mode=request.mode,
            phase_times=phase_times,
            packed_tokens=packed_tokens,
            raw_tokens=all_tokens,
            saving_pct=saving_pct,
            selected_count=len(selected),
            changed_count=len(all_changed),
        )

        return PackResult(
            pack=pack_obj,
            out_path=out_path,
            phase_times=phase_times,
            packed_tokens=packed_tokens,
            raw_tokens=all_tokens,
            saving_pct=saving_pct,
            changed_files=sorted(all_changed),
            scan_result=scan_result,
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
