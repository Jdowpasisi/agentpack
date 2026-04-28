"""Tests for configurable scoring weights."""
import pytest
from pathlib import Path
from agentpack.core.config import ScoringWeights
from agentpack.analysis.ranking import score_files
from agentpack.core.models import FileInfo


def _fi(path: str) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path("/nonexistent") / path,
        size_bytes=400,
        estimated_tokens=100,
        language="python",
    )


def test_custom_weights_applied():
    files = [_fi("auth/session.py")]
    w = ScoringWeights(modified=999)
    scored = score_files(
        files,
        changed_paths={"auth/session.py"},
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=set(),
        weights=w,
    )
    assert scored[0][1] >= 999


def test_default_weights_used_when_none():
    files = [_fi("auth/session.py")]
    scored = score_files(
        files,
        changed_paths={"auth/session.py"},
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=set(),
        weights=None,
    )
    assert scored[0][1] >= 100


def test_zero_penalty_for_large_file():
    fi = FileInfo(
        path="big.py",
        abs_path=Path("/nonexistent/big.py"),
        size_bytes=100000,
        estimated_tokens=5000,
        too_large=True,
        language="python",
    )
    w = ScoringWeights(large_unrelated_penalty=0)
    scored = score_files(
        [fi],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"big"},
        weights=w,
    )
    # With penalty=0, the filename match should still score positively
    assert scored[0][1] >= 0
