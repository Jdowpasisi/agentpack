import stat
from pathlib import Path
import pytest

from agentpack.core.git_hooks import install_git_hooks, remove_git_hooks, _HOOK_EVENTS


def _make_git_repo(tmp_path: Path) -> Path:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


class TestInstallGitHooks:
    def test_creates_hooks_in_empty_repo(self, tmp_path):
        root = _make_git_repo(tmp_path)
        results = install_git_hooks(root, agent="cursor")
        assert set(results.keys()) == set(_HOOK_EVENTS)
        for event in _HOOK_EVENTS:
            hook = root / ".git" / "hooks" / event
            assert hook.exists()
            assert "agentpack pack" in hook.read_text()
            assert "cursor" in hook.read_text()

    def test_hooks_are_executable(self, tmp_path):
        root = _make_git_repo(tmp_path)
        install_git_hooks(root, agent="cursor")
        for event in _HOOK_EVENTS:
            hook = root / ".git" / "hooks" / event
            assert hook.stat().st_mode & stat.S_IXUSR

    def test_idempotent(self, tmp_path):
        root = _make_git_repo(tmp_path)
        install_git_hooks(root, agent="cursor")
        results2 = install_git_hooks(root, agent="cursor")
        for action in results2.values():
            assert action == "unchanged"

    def test_appends_to_existing_hook(self, tmp_path):
        root = _make_git_repo(tmp_path)
        hook = root / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\necho 'existing hook'\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        results = install_git_hooks(root, agent="windsurf")
        assert results["post-commit"] == "appended"
        content = hook.read_text()
        assert "existing hook" in content
        assert "agentpack pack" in content

    def test_returns_empty_if_no_git_dir(self, tmp_path):
        results = install_git_hooks(tmp_path, agent="cursor")
        assert results == {}

    def test_agent_name_in_hook(self, tmp_path):
        root = _make_git_repo(tmp_path)
        install_git_hooks(root, agent="codex")
        hook = root / ".git" / "hooks" / "post-commit"
        assert "--agent codex" in hook.read_text()


class TestRemoveGitHooks:
    def test_removes_installed_hooks(self, tmp_path):
        root = _make_git_repo(tmp_path)
        install_git_hooks(root, agent="cursor")
        results = remove_git_hooks(root)
        for event in _HOOK_EVENTS:
            hook = root / ".git" / "hooks" / event
            assert not hook.exists() or "agentpack" not in hook.read_text()

    def test_preserves_existing_content(self, tmp_path):
        root = _make_git_repo(tmp_path)
        hook = root / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\necho 'keep me'\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        install_git_hooks(root, agent="cursor")
        remove_git_hooks(root)
        assert hook.exists()
        assert "keep me" in hook.read_text()
        assert "agentpack" not in hook.read_text()

    def test_noop_if_not_installed(self, tmp_path):
        root = _make_git_repo(tmp_path)
        results = remove_git_hooks(root)
        assert all(v == "unchanged" for v in results.values())
