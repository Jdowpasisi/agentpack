"""Tests for mcp_server.py — _repo_root, _truncate_to_budget, get_context staleness, explain_file, get_related_files, get_stats."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


from agentpack.mcp_server import (
    _repo_root,
    _truncate_to_budget,
    _get_context_impl,
    _get_stats_impl,
    _explain_file_impl,
    _get_related_files_impl,
)


# ---------------------------------------------------------------------------
# _repo_root
# ---------------------------------------------------------------------------

def test_repo_root_finds_agentpack_dir(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    deep = tmp_path / "src" / "pkg"
    deep.mkdir(parents=True)
    with patch("agentpack.mcp_server.Path") as mock_path_cls:
        mock_path_cls.cwd.return_value = deep
        # Use real Path for parents traversal
        with patch.object(Path, "cwd", return_value=deep):
            result = _repo_root()
    assert result == tmp_path


def test_repo_root_fallback_to_cwd(tmp_path):
    with patch.object(Path, "cwd", return_value=tmp_path):
        result = _repo_root()
    assert result == tmp_path


# ---------------------------------------------------------------------------
# _truncate_to_budget
# ---------------------------------------------------------------------------

def _make_pack(n_files: int = 5, chars_per_file: int = 500) -> str:
    header = "# AgentPack Context for Claude\n\n## Token Stats\n\nRaw: 10000\n\n"
    file_section = "\n## File Context\n\n"
    for i in range(n_files):
        file_section += f"\n### src/file_{i}.py\n\n" + "x" * chars_per_file + "\n"
    return header + file_section


def test_truncate_noop_when_under_budget():
    short = "x" * 100
    assert _truncate_to_budget(short, max_tokens=1000) == short


def test_truncate_applies_when_over_budget():
    large = _make_pack(n_files=20, chars_per_file=1000)
    result = _truncate_to_budget(large, max_tokens=10)
    assert len(result) <= 10 * 4 + 300  # budget_chars + truncation message overhead
    assert "Truncated" in result


def test_truncate_keeps_header():
    large = _make_pack(n_files=20, chars_per_file=500)
    result = _truncate_to_budget(large, max_tokens=100)
    assert "# AgentPack Context for Claude" in result
    assert "## Token Stats" in result


def test_truncate_message_mentions_omitted_files():
    large = _make_pack(n_files=20, chars_per_file=500)
    result = _truncate_to_budget(large, max_tokens=50)
    assert "files omitted" in result or "Truncated" in result


def test_truncate_no_truncation_marker_when_fits():
    small = _make_pack(n_files=1, chars_per_file=10)
    result = _truncate_to_budget(small, max_tokens=10000)
    assert "Truncated" not in result


# ---------------------------------------------------------------------------
# get_context — staleness signal
# ---------------------------------------------------------------------------

def _write_metadata(root: Path, root_hash: str, token_estimate: int = 1000) -> None:
    meta = {
        "context_path": ".agentpack/context.claude.md",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_root_hash": root_hash,
        "task": "test",
        "agent": "claude",
        "mode": "balanced",
        "budget": 25000,
        "token_estimate": token_estimate,
    }
    (root / ".agentpack").mkdir(exist_ok=True)
    (root / ".agentpack" / "pack_metadata.json").write_text(json.dumps(meta))


def _write_snapshot(root: Path, root_hash: str) -> None:
    snap = {"version": 1, "root_hash": root_hash, "created_at": "2026-01-01T00:00:00+00:00", "files": {}}
    (root / ".agentpack" / "snapshots").mkdir(parents=True, exist_ok=True)
    (root / ".agentpack" / "snapshots" / "latest.json").write_text(json.dumps(snap))


def test_get_context_returns_empty_when_no_pack(tmp_path):
    assert _get_context_impl(tmp_path) == ""


def test_get_context_fresh_when_hashes_match(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "context.claude.md").write_text("# pack content")
    _write_metadata(tmp_path, root_hash="abc123", token_estimate=5000)
    _write_snapshot(tmp_path, root_hash="abc123")

    result = _get_context_impl(tmp_path)
    assert "Context is fresh" in result
    assert "5,000 tokens" in result
    assert "# pack content" in result


def test_get_context_stale_when_hashes_differ(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "context.claude.md").write_text("# pack content")
    _write_metadata(tmp_path, root_hash="abc123")
    _write_snapshot(tmp_path, root_hash="def456")

    result = _get_context_impl(tmp_path)
    assert "Stale context" in result
    assert "pack_context()" in result


def test_get_context_stale_when_no_metadata(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "context.claude.md").write_text("# pack content")
    _write_snapshot(tmp_path, root_hash="abc123")

    result = _get_context_impl(tmp_path)
    assert "Stale context" in result


def test_get_context_stale_when_no_snapshot(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "context.claude.md").write_text("# pack content")
    _write_metadata(tmp_path, root_hash="abc123")

    result = _get_context_impl(tmp_path)
    assert "Stale context" in result


# ---------------------------------------------------------------------------
# _get_stats_impl
# ---------------------------------------------------------------------------

def _write_metadata_full(root: Path, **overrides) -> None:
    meta = {
        "context_path": ".agentpack/context.claude.md",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_root_hash": "abc",
        "task": "fix login bug",
        "agent": "claude",
        "mode": "balanced",
        "budget": 25000,
        "token_estimate": 4200,
    }
    meta.update(overrides)
    (root / ".agentpack").mkdir(exist_ok=True)
    (root / ".agentpack" / "pack_metadata.json").write_text(json.dumps(meta))


def test_get_stats_no_metadata(tmp_path):
    result = _get_stats_impl(tmp_path)
    assert "No pack metadata found" in result


def test_get_stats_returns_task_and_tokens(tmp_path):
    _write_metadata_full(tmp_path)
    result = _get_stats_impl(tmp_path)
    assert "fix login bug" in result
    assert "4,200" in result
    assert "claude" in result
    assert "balanced" in result


def test_get_stats_includes_metrics_when_present(tmp_path):
    _write_metadata_full(tmp_path)
    metrics = {
        "ts": "2026-01-01T00:00:00+00:00",
        "task": "fix login bug",
        "mode": "balanced",
        "packed_tokens": 4200,
        "raw_tokens": 50000,
        "saving_pct": 91.6,
        "selected_files": 8,
        "changed_files": 3,
        "selected_paths": [],
        "phases": {},
        "total_s": 1.23,
    }
    (tmp_path / ".agentpack" / "metrics.jsonl").write_text(json.dumps(metrics) + "\n")
    result = _get_stats_impl(tmp_path)
    assert "Last pack run" in result
    assert "91.6%" in result
    assert "1.23s" in result


def test_get_stats_includes_selection_f1_when_present(tmp_path):
    _write_metadata_full(tmp_path)
    metrics = {
        "task": "t", "mode": "balanced", "packed_tokens": 1, "raw_tokens": 100,
        "saving_pct": 99.0, "selected_files": 1, "changed_files": 0,
        "selected_paths": [], "phases": {}, "total_s": 0.5,
        "selection_f1": 0.875,
    }
    (tmp_path / ".agentpack" / "metrics.jsonl").write_text(json.dumps(metrics) + "\n")
    result = _get_stats_impl(tmp_path)
    assert "0.875" in result


def test_get_stats_corrupt_metadata(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "pack_metadata.json").write_text("not json")
    result = _get_stats_impl(tmp_path)
    assert "Failed to read pack metadata" in result


# ---------------------------------------------------------------------------
# _explain_file_impl — uses mocked PackPlanner
# ---------------------------------------------------------------------------

def _make_mock_plan(path: str, score: float = 150.0, reasons: list[str] | None = None):
    from agentpack.core.models import DependencyGraph, DependencyNode, ScanResult, FileInfo

    reasons = reasons or ["modified"]
    fi = MagicMock()
    fi.path = path
    fi.estimated_tokens = 300

    plan = MagicMock()
    plan.scored = [(fi, score, reasons)]
    plan.selected = []
    plan.summaries = {}
    plan.scan_result = MagicMock()
    plan.scan_result.packable = [fi]

    graph = DependencyGraph()
    graph.nodes[path] = DependencyNode(
        path=path,
        imports=["src/other.py"],
        imported_by=["src/main.py"],
    )
    plan.dep_graph = graph
    return plan


def test_explain_file_unknown_path(tmp_path):
    mock_plan = _make_mock_plan("src/auth.py")
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _explain_file_impl(tmp_path, "nonexistent.py", task="test task")
    assert "not found in scoring data" in result


def test_explain_file_returns_score_and_signals(tmp_path):
    mock_plan = _make_mock_plan("src/auth.py", score=200.0, reasons=["modified", "staged"])
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _explain_file_impl(tmp_path, "src/auth.py", task="fix auth bug")
    assert "## src/auth.py" in result
    assert "200" in result
    assert "modified" in result
    assert "staged" in result
    assert "fix auth bug" in result


def test_explain_file_falls_back_to_task_md(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task.md").write_text("add stripe webhook")
    mock_plan = _make_mock_plan("src/pay.py")
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _explain_file_impl(tmp_path, "src/pay.py")
    assert "add stripe webhook" in result


def test_explain_file_shows_dep_graph(tmp_path):
    mock_plan = _make_mock_plan("src/auth.py")
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _explain_file_impl(tmp_path, "src/auth.py", task="t")
    assert "src/other.py" in result
    assert "src/main.py" in result


# ---------------------------------------------------------------------------
# _get_related_files_impl — uses mocked PackPlanner
# ---------------------------------------------------------------------------

def _make_graph_plan(nodes: dict[str, dict]):
    from agentpack.core.models import DependencyGraph, DependencyNode

    graph = DependencyGraph()
    for path, data in nodes.items():
        graph.nodes[path] = DependencyNode(
            path=path,
            imports=data.get("imports", []),
            imported_by=data.get("imported_by", []),
            tests=data.get("tests", []),
        )
    plan = MagicMock()
    plan.dep_graph = graph
    return plan


def test_get_related_files_no_neighbours(tmp_path):
    plan = _make_graph_plan({"src/lone.py": {}})
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = plan
        result = _get_related_files_impl(tmp_path, "src/lone.py")
    assert "No related files found" in result


def test_get_related_files_direct_imports(tmp_path):
    plan = _make_graph_plan({
        "src/a.py": {"imports": ["src/b.py"], "imported_by": ["src/c.py"]},
    })
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = plan
        result = _get_related_files_impl(tmp_path, "src/a.py", depth=1)
    assert "src/b.py" in result
    assert "src/c.py" in result
    assert "imports" in result
    assert "imported_by" in result


def test_get_related_files_depth2(tmp_path):
    plan = _make_graph_plan({
        "src/a.py": {"imports": ["src/b.py"]},
        "src/b.py": {"imports": ["src/c.py"]},
    })
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = plan
        result = _get_related_files_impl(tmp_path, "src/a.py", depth=2)
    assert "src/b.py" in result
    assert "src/c.py" in result
    assert "hop 2" in result


def test_get_related_files_depth_clamped(tmp_path):
    plan = _make_graph_plan({"src/a.py": {}})
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = plan
        # depth=99 should clamp to 2, not crash
        result = _get_related_files_impl(tmp_path, "src/a.py", depth=99)
    assert "No related files found" in result


def test_get_related_files_excludes_self(tmp_path):
    plan = _make_graph_plan({
        "src/a.py": {"imports": ["src/a.py", "src/b.py"]},
    })
    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.adapters.detect.detect_agent", return_value="generic"):
        MockPlanner.return_value.plan.return_value = plan
        result = _get_related_files_impl(tmp_path, "src/a.py", depth=1)
    # src/a.py should not appear as its own neighbour
    lines = [l for l in result.splitlines() if "src/a.py" in l and "Related files for" not in l]
    assert not lines
