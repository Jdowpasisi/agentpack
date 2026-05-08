"""Tests for mcp_server.py — _repo_root, _truncate_to_budget, get_context staleness."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agentpack.mcp_server import _repo_root, _truncate_to_budget, _get_context_impl


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
        import agentpack.mcp_server as mod
        original_cwd = Path.cwd
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
