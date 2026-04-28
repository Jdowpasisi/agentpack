import pytest
from agentpack.core.diff import diff_snapshots


def _snap(files: dict[str, str]) -> dict:
    return {
        "version": 1,
        "root_hash": "x",
        "created_at": "2026-01-01",
        "files": {p: {"hash": h, "size_bytes": 100, "estimated_tokens": 25} for p, h in files.items()},
    }


def test_all_added_when_no_previous():
    new = _snap({"a.py": "h1", "b.py": "h2"})
    result = diff_snapshots(None, new)
    assert set(result.added) == {"a.py", "b.py"}
    assert result.modified == []
    assert result.deleted == []


def test_detects_modified():
    old = _snap({"a.py": "h1"})
    new = _snap({"a.py": "h2"})
    result = diff_snapshots(old, new)
    assert "a.py" in result.modified
    assert result.added == []


def test_detects_deleted():
    old = _snap({"a.py": "h1", "b.py": "h2"})
    new = _snap({"a.py": "h1"})
    result = diff_snapshots(old, new)
    assert "b.py" in result.deleted


def test_unchanged():
    old = _snap({"a.py": "h1"})
    new = _snap({"a.py": "h1"})
    result = diff_snapshots(old, new)
    assert "a.py" in result.unchanged
    assert result.modified == []
