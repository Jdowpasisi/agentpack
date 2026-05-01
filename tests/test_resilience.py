"""Tests for graceful handling of corrupted state files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentpack.core.cache import load_summary, save_summary
from agentpack.core.config import load_config
from agentpack.core.context_pack import load_pack_metadata
from agentpack.core.models import FileSummary
from agentpack.core.snapshot import load_snapshot


# ---------------------------------------------------------------------------
# config.toml corruption
# ---------------------------------------------------------------------------

def test_corrupt_config_returns_defaults(tmp_path):
    cfg_dir = tmp_path / ".agentpack"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text("[[invalid toml{{")
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = load_config(tmp_path)
    assert cfg.context.default_budget == 25000
    assert any("Failed to parse" in str(warning.message) for warning in w)


def test_valid_config_partial_keys(tmp_path):
    cfg_dir = tmp_path / ".agentpack"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text('[context]\ndefault_budget = 10000\n')
    cfg = load_config(tmp_path)
    assert cfg.context.default_budget == 10000
    assert cfg.context.default_mode == "balanced"


# ---------------------------------------------------------------------------
# snapshot corruption
# ---------------------------------------------------------------------------

def test_corrupt_snapshot_returns_none(tmp_path):
    snap_dir = tmp_path / ".agentpack" / "snapshots"
    snap_dir.mkdir(parents=True)
    (snap_dir / "latest.json").write_text("{invalid json")
    assert load_snapshot(tmp_path) is None


def test_missing_snapshot_returns_none(tmp_path):
    assert load_snapshot(tmp_path) is None


# ---------------------------------------------------------------------------
# cache corruption
# ---------------------------------------------------------------------------

def test_corrupt_cache_returns_none_and_deletes(tmp_path):
    cache_dir = tmp_path / ".agentpack" / "cache"
    cache_dir.mkdir(parents=True)

    summary = FileSummary(
        path="src/foo.py", hash="abc123", language="python",
        provider="offline", schema_version=1,
        summary="Does foo things.", imports=[], symbols=[],
    )
    save_summary(tmp_path, summary)

    # Corrupt the cache file
    for f in cache_dir.iterdir():
        f.write_text("{bad json")

    result = load_summary(tmp_path, "src/foo.py", "abc123", "offline", 1)
    assert result is None
    # Corrupt file should be deleted
    assert list(cache_dir.iterdir()) == []


def test_missing_cache_returns_none(tmp_path):
    result = load_summary(tmp_path, "src/foo.py", "abc123", "offline", 1)
    assert result is None


# ---------------------------------------------------------------------------
# pack_metadata corruption
# ---------------------------------------------------------------------------

def test_corrupt_pack_metadata_returns_none(tmp_path):
    meta_dir = tmp_path / ".agentpack"
    meta_dir.mkdir()
    (meta_dir / "pack_metadata.json").write_text("{corrupt")
    assert load_pack_metadata(tmp_path) is None


def test_missing_pack_metadata_returns_none(tmp_path):
    assert load_pack_metadata(tmp_path) is None


def test_valid_pack_metadata_round_trips(tmp_path):
    from agentpack.core.context_pack import save_pack_metadata
    meta_dir = tmp_path / ".agentpack"
    meta_dir.mkdir()
    save_pack_metadata(
        tmp_path, context_path=".agentpack/context.claude.md",
        snapshot_root_hash="abc", task="fix bug", agent="claude",
        mode="balanced", budget=25000, token_estimate=1000,
    )
    meta = load_pack_metadata(tmp_path)
    assert meta is not None
    assert meta["task"] == "fix bug"
    assert meta["token_estimate"] == 1000
