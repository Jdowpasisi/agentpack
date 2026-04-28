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
