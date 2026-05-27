"""Tests for git module — graceful fallback when not in a git repo."""
import subprocess
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


def test_co_changed_files_graceful(tmp_path):
    result = git.co_changed_files(tmp_path, {"src/auth/session.py"})
    assert isinstance(result, dict)
    assert result == {}


def test_untracked_graceful(tmp_path):
    result = git.untracked_files(tmp_path)
    assert isinstance(result, set)


def test_working_tree_summary_counts_statuses(tmp_path):
    repo = _make_git_repo(tmp_path)
    (repo / "tracked.py").write_text("v1")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    (repo / "staged.py").write_text("new")
    subprocess.run(["git", "add", "staged.py"], cwd=repo, check=True, capture_output=True)
    (repo / "tracked.py").write_text("v2")
    (repo / "untracked.py").write_text("new")

    summary = git.working_tree_summary(repo)

    assert summary["branch"] in {"main", "master"}
    assert summary["staged_count"] == 1
    assert summary["unstaged_count"] == 1
    assert summary["untracked_count"] == 1
    assert "untracked.py" in summary["dirty_sample"]


def test_dirty_files_preserves_modified_tracked_path(tmp_path):
    repo = _make_git_repo(tmp_path)
    (repo / "README.md").write_text("v1")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    (repo / "README.md").write_text("v2")

    assert "README.md" in git.dirty_files(repo)
    assert "EADME.md" not in git.dirty_files(repo)


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


def test_staged_files_graceful(tmp_path):
    result = git.staged_files(tmp_path)
    assert isinstance(result, set)
    assert len(result) == 0


def test_infer_task_with_source_non_git_returns_fallback(tmp_path):
    task, source = git.infer_task_with_source(tmp_path)
    assert task == "general development"
    assert source == "fallback"


def test_infer_task_with_source_returns_tuple():
    task, source = git.infer_task_with_source(Path("."))
    assert isinstance(task, str) and len(task) > 0
    assert isinstance(source, str) and len(source) > 0


def _make_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_staged_files_beats_recently_modified(tmp_path):
    repo = _make_git_repo(tmp_path)

    # Create initial commit so HEAD exists
    (repo / "old.py").write_text("old")
    subprocess.run(["git", "add", "old.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    # Stage a new file — this is the "current task" signal
    (repo / "src").mkdir()
    (repo / "src" / "payment.py").write_text("def pay(): pass")
    subprocess.run(["git", "add", "src/payment.py"], cwd=repo, check=True, capture_output=True)

    task, source = git.infer_task_with_source(repo)
    assert source in ("staged", "branch+staged")
    assert "payment" in task


def test_co_changed_files_counts_neighbors(tmp_path):
    repo = _make_git_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "session.py").write_text("v1")
    (repo / "tests" / "test_session.py").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial session"], cwd=repo, check=True, capture_output=True)

    (repo / "src" / "session.py").write_text("v2")
    (repo / "tests" / "test_session.py").write_text("v2")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix session"], cwd=repo, check=True, capture_output=True)

    result = git.co_changed_files(repo, {"src/session.py"})
    assert result["tests/test_session.py"] >= 1
    assert "src/session.py" not in result


def test_source_label_in_valid_set():
    valid = {"branch+staged", "staged", "branch+unstaged", "branch+commit", "branch",
             "unstaged+commit", "unstaged", "commits", "recently_modified", "fallback"}
    _, source = git.infer_task_with_source(Path("."))
    assert source in valid
