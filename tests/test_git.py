"""Tests for git module — graceful fallback when not in a git repo."""
import pytest
from pathlib import Path
from agentpack.core import git


def test_not_git_repo(tmp_path):
    assert not git.is_git_repo(tmp_path)


def test_changed_files_graceful(tmp_path):
    result = git.changed_files(tmp_path)
    assert isinstance(result, set)
    assert len(result) == 0


def test_changed_files_since_graceful(tmp_path):
    result = git.changed_files_since(tmp_path, "HEAD~1")
    assert isinstance(result, set)


def test_recently_modified_graceful(tmp_path):
    result = git.recently_modified_files(tmp_path)
    assert isinstance(result, list)
    assert len(result) == 0


def test_untracked_graceful(tmp_path):
    result = git.untracked_files(tmp_path)
    assert isinstance(result, set)


def test_infer_task_non_git_returns_fallback(tmp_path):
    result = git.infer_task_from_git(tmp_path)
    assert result == "general development"


def test_infer_task_returns_string(tmp_path):
    result = git.infer_task_from_git(tmp_path)
    assert isinstance(result, str)
    assert len(result) > 0


def test_infer_task_from_real_repo():
    result = git.infer_task_from_git(Path("."))
    assert isinstance(result, str)
    assert len(result) > 0


def test_topic_from_paths_returns_none_for_empty():
    assert git._topic_from_paths(set()) is None


def test_topic_from_paths_extracts_stems():
    result = git._topic_from_paths({"src/auth/session.py", "src/auth/token.py"})
    assert result is not None
    assert "session" in result or "token" in result or "auth" in result


def test_topic_from_paths_deduplicates():
    result = git._topic_from_paths({"src/auth/session.py", "src/auth/session.py"})
    assert result is not None
    assert result.count("session") == 1


def test_topic_from_paths_skips_init():
    result = git._topic_from_paths({"src/auth/__init__.py"})
    # __init__ stem is in _SKIP, so topic comes from dir or is None
    assert result is None or "auth" in result
