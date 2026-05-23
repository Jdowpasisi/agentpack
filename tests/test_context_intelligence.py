from __future__ import annotations

from pathlib import Path

from agentpack.analysis.repo_map import build_repo_map
from agentpack.analysis.task_classifier import classify_task
from agentpack.application.pack_service import (
    _apply_history_penalties,
    _apply_no_live_precision_guard,
    _apply_scope_penalties,
    _compute_delta_summary,
    _filter_co_changed_paths,
    _resolve_effective_mode,
    _strict_summary_selection,
    _guarded_weak_signal_cap,
    _guarded_summary_cap,
    _guarded_summary_score_floor,
)
from agentpack.core.config import DEFAULT_CONFIG
from agentpack.core.context_pack import _select_diff_hunks, select_files
from agentpack.core.models import DependencyGraph, FileInfo, SelectedFile
from agentpack.renderers.markdown import render_claude
from agentpack.summaries.offline import summarize


def _fi(tmp_path: Path, path: str, content: str = "def x():\n    pass\n", tokens: int = 100) -> FileInfo:
    abs_path = tmp_path / path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return FileInfo(
        path=path,
        abs_path=abs_path,
        language="python",
        size_bytes=abs_path.stat().st_size,
        estimated_tokens=tokens,
        hash="h1",
        content=content,
    )


def test_task_classifier_identifies_release_and_hooks():
    result = classify_task("fix hooks and release new package version")
    assert result.kind in {"bugfix", "release", "infra"}
    assert result.confidence >= 0.45
    assert result.signals


def test_repo_map_groups_scored_files(tmp_path):
    service = _fi(tmp_path, "src/agentpack/service.py")
    tests = _fi(tmp_path, "tests/test_service.py")
    graph = DependencyGraph()
    summaries = {
        service.path: {"role": "pack service"},
        tests.path: {"role": "tests"},
    }

    repo_map = build_repo_map(
        files=[service, tests],
        scored=[(service, 200.0, ["task match"]), (tests, 80.0, ["test"])],
        summaries=summaries,
        dep_graph=graph,
        changed_paths={service.path},
        budget_tokens=300,
    )

    assert "Task repo map" in repo_map
    assert "src/agentpack" in repo_map
    assert "service.py" in repo_map


def test_diff_hunks_prefer_keyword_matches():
    diff = "\n".join([
        "diff --git a/a.py b/a.py",
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1,3 +1,3 @@",
        "-old = 1",
        "+new = 2",
        "@@ -20,3 +20,3 @@",
        "-hooks = []",
        "+hooks = install_hooks()",
    ])

    selected = _select_diff_hunks(diff, max_tokens=35, keywords={"hooks"})

    assert "install_hooks" in selected
    assert "diff --git" in selected


def test_value_optimizer_downgrades_changed_file_to_fit_budget(tmp_path):
    content = "\n".join(f"def f{i}(): pass" for i in range(200))
    fi = _fi(tmp_path, "src/large.py", content=content, tokens=3000)
    summaries = {
        fi.path: {
            "summary": "Large implementation file.",
            "imports": ["os"],
            "symbols": [{
                "name": "f1",
                "kind": "function",
                "start_line": 1,
                "end_line": 1,
                "signature": "def f1(): pass",
            }],
        }
    }

    selected, receipts = select_files(
        files=[fi],
        scored=[(fi, 200.0, ["filename keyword match"])],
        changed_paths={fi.path},
        summaries=summaries,
        mode="balanced",
        budget=80,
        max_file_tokens=4000,
    )

    assert selected
    assert selected[0].include_mode in {"summary", "skeleton"}
    assert any("value optimizer downgraded" in reason for reason in selected[0].reasons)
    assert any(receipt.action == "summarized" for receipt in receipts)


def test_delta_summary_reports_selected_changes():
    previous = {
        "selected_files_meta": [
            {"path": "old.py", "mode": "full"},
            {"path": "same.py", "mode": "summary"},
        ]
    }
    current = [
        SelectedFile(path="same.py", score=1, include_mode="skeleton", reasons=[]),
        SelectedFile(path="new.py", score=1, include_mode="summary", reasons=[]),
    ]

    delta = _compute_delta_summary(previous, current, {"new.py"})

    assert "+1 new" in delta
    assert "-1 removed" in delta
    assert "Mode changed" in delta


def test_history_penalties_downrank_previous_noise(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        '{"selection_noise_paths":["src/noisy.py"]}\n'
        '{"selection_noise_paths":["src/noisy.py"]}\n',
        encoding="utf-8",
    )
    noisy = _fi(tmp_path, "src/noisy.py")
    useful = _fi(tmp_path, "src/useful.py")

    adjusted = _apply_history_penalties(
        tmp_path,
        [(noisy, 100.0, ["keyword"]), (useful, 95.0, ["keyword"])],
        changed_paths=set(),
    )

    assert adjusted[0][1] < 100.0
    assert "history noise penalty" in adjusted[0][2][-1]


def test_history_penalties_suppress_repeat_noise_for_broad_tasks(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join('{"selection_noise_paths":["src/noisy.py"]}' for _ in range(4)),
        encoding="utf-8",
    )
    noisy = _fi(tmp_path, "src/noisy.py")
    strong = _fi(tmp_path, "src/strong.py")

    adjusted = _apply_history_penalties(
        tmp_path,
        [
            (noisy, 100.0, ["filename keyword match"]),
            (strong, 100.0, ["filename keyword match", "content keyword match (2)"]),
        ],
        changed_paths=set(),
        generic_ratio=0.6,
    )

    scores = {fi.path: (score, reasons) for fi, score, reasons in adjusted}
    assert scores["src/noisy.py"][0] == 0.0
    assert "repeat noise path suppressed" in scores["src/noisy.py"][1]
    assert scores["src/strong.py"][0] > 0.0


def test_history_penalties_suppress_repeat_weak_noise_even_without_broad_task(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join('{"selection_noise_paths":["src/noisy.py"]}' for _ in range(6)),
        encoding="utf-8",
    )
    noisy = _fi(tmp_path, "src/noisy.py")

    adjusted = _apply_history_penalties(
        tmp_path,
        [(noisy, 100.0, ["filename keyword match", "matched role keyword: helper"])],
        changed_paths=set(),
        generic_ratio=0.1,
    )

    assert adjusted[0][1] == 0.0
    assert "repeat weak-noise path suppressed" in adjusted[0][2]


def test_cochange_filter_requires_repetition_and_skips_noisy_paths(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join(
            '{"selection_noise_paths":["src/noisy.py"]}'
            for _ in range(5)
        ),
        encoding="utf-8",
    )

    filtered = _filter_co_changed_paths(
        tmp_path,
        {
            "src/oneoff.py": 1,
            "src/noisy.py": 8,
            "src/useful.py": 2,
        },
    )

    assert filtered == {"src/useful.py": 2}


def test_summary_precision_guard_tightens_noisy_summaries(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        '{"selection_token_precision_summary":0.0}\n'
        '{"selection_token_precision_summary":0.0}\n'
        '{"selection_token_precision_summary":0.0}\n',
        encoding="utf-8",
    )

    floor = _guarded_summary_score_floor(tmp_path, DEFAULT_CONFIG, "balanced", 0.0)
    cap = _guarded_summary_cap(tmp_path, DEFAULT_CONFIG, "balanced", 0.0)
    no_live_floor = _guarded_summary_score_floor(
        tmp_path, DEFAULT_CONFIG, "balanced", 0.0, no_live_changes=True
    )
    no_live_cap = _guarded_summary_cap(
        tmp_path, DEFAULT_CONFIG, "balanced", 0.0, no_live_changes=True
    )

    assert floor == DEFAULT_CONFIG.context.min_summary_score + 80
    assert cap == 5
    assert no_live_floor == DEFAULT_CONFIG.context.min_summary_score + 140
    assert no_live_cap == -1


def test_weak_signal_cap_tightens_for_broad_no_live_low_precision_runs(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join('{"selection_token_precision":0.05}' for _ in range(3)),
        encoding="utf-8",
    )

    cap = _guarded_weak_signal_cap(
        tmp_path,
        "balanced",
        0.6,
        no_live_changes=True,
        effective_budget=10000,
    )

    assert cap == 1


def test_effective_mode_auto_tightens_balanced_to_minimal_for_no_live_noise(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join([
            '{"selection_token_precision":0.12,"selection_token_precision_summary":0.0}',
            '{"selection_token_precision":0.10,"selection_token_precision_summary":0.0}',
            '{"selection_token_precision":0.08,"selection_token_precision_summary":0.0}',
        ]),
        encoding="utf-8",
    )

    mode, warning = _resolve_effective_mode(
        tmp_path,
        "balanced",
        0.45,
        no_live_changes=True,
    )

    assert mode == "minimal"
    assert warning is not None


def test_scope_penalties_suppress_backend_leak_for_frontend_only_task(tmp_path):
    frontend = _fi(tmp_path, "src/app/page.tsx")
    backend = _fi(tmp_path, "backend/src/services/analysis_job.py")

    adjusted = _apply_scope_penalties(
        [
            (frontend, 120.0, ["modified", "content keyword match (3)"]),
            (backend, 110.0, ["filename keyword match", "symbol keyword match"]),
        ],
        "frontend public seo preview signup flow",
        {"src/app/page.tsx"},
        generic_ratio=0.4,
    )

    scores = {fi.path: (score, reasons) for fi, score, reasons in adjusted}
    assert scores["backend/src/services/analysis_job.py"][0] == 0.0
    assert "frontend-scope backend suppression" in scores["backend/src/services/analysis_job.py"][1]


def test_strict_summary_selection_enabled_for_dead_summary_precision(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join('{"selection_token_precision_summary":0.0}' for _ in range(3)),
        encoding="utf-8",
    )

    assert _strict_summary_selection(tmp_path) is True


def test_no_live_precision_guard_dampens_filename_only_matches(tmp_path):
    filename_only = _fi(tmp_path, "src/release.py")
    corroborated = _fi(tmp_path, "src/auth.py")

    adjusted = _apply_no_live_precision_guard(
        [
            (filename_only, 100.0, ["filename keyword match"]),
            (corroborated, 90.0, ["filename keyword match", "content keyword match (2)"]),
        ],
        generic_ratio=0.4,
    )

    scores = {fi.path: (score, reasons) for fi, score, reasons in adjusted}
    assert scores["src/release.py"][0] < 40
    assert any(
        reason in {"no-live filename-only dampening", "broad-task weak-signal dampening"}
        for reason in scores["src/release.py"][1]
    )
    assert scores["src/auth.py"][0] == 90.0


def test_no_live_precision_guard_hits_broad_task_meta_matches_harder(tmp_path):
    generic = _fi(tmp_path, "src/__init__.py")
    specific = _fi(tmp_path, "src/auth/session.py")

    adjusted = _apply_no_live_precision_guard(
        [
            (generic, 120.0, ["filename keyword match", "matched role keyword: init"]),
            (specific, 110.0, ["filename keyword match", "content keyword match (2)"]),
        ],
        generic_ratio=0.7,
    )

    scores = {fi.path: (score, reasons) for fi, score, reasons in adjusted}
    assert scores["src/__init__.py"][0] < 30
    assert "broad-task weak-signal dampening" in scores["src/__init__.py"][1]
    assert scores["src/auth/session.py"][0] == 110.0


def test_offline_summary_includes_richer_fields(tmp_path):
    fi = _fi(
        tmp_path,
        "src/commands/run.py",
        content="import subprocess\n\ndef main():\n    raise RuntimeError('boom')\n",
    )
    summary = summarize(fi.path, fi.abs_path, "python", "h1")

    assert summary.role
    assert "subprocess" in summary.side_effects
    assert summary.error_paths
    assert summary.test_hints


def test_render_includes_repo_map_and_delta():
    from agentpack.core.models import ContextPack

    pack = ContextPack(
        task="fix hooks",
        agent="generic",
        mode="balanced",
        task_class="bugfix",
        budget=1000,
        token_estimate=100,
        raw_repo_tokens=1000,
        after_ignore_tokens=900,
        estimated_savings_percent=90.0,
        repo_map="Task repo map:\n- src: hooks",
        delta_summary="Selected delta: +1 new",
        changed_files=[],
        selected_files=[],
        receipts=[],
    )

    rendered = render_claude(pack)

    assert "## Repo Map" in rendered
    assert "## Delta Since Last Pack" in rendered
    assert "Task repo map" in rendered
