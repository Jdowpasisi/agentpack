from __future__ import annotations

from pathlib import Path

from agentpack.analysis.repo_map import build_repo_map
from agentpack.analysis.task_classifier import classify_task
from agentpack.application.pack_service import (
    _apply_history_penalties,
    _compute_delta_summary,
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

    assert floor == DEFAULT_CONFIG.context.min_summary_score + 80
    assert cap == 5


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
