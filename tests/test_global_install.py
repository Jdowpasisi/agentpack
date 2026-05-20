import stat

from agentpack.integrations.global_install import (
    install_git_template_hooks,
    remove_git_template_hooks,
    install_shell_hook,
    remove_shell_hook,
    _HOOK_SCRIPTS,
    _AGENTPACK_MARKER,
    _SHELL_MARKER_START,
    _SHELL_MARKER_END,
    _detect_rc_file,
)


# ---------------------------------------------------------------------------
# Git template hooks
# ---------------------------------------------------------------------------

class TestGitTemplateHooks:
    def test_creates_all_hooks(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"

        install_git_template_hooks()
        for name in _HOOK_SCRIPTS:
            hook = tmp_path / ".git-templates" / "hooks" / name
            assert hook.exists(), f"{name} not created"
            content = hook.read_text()
            assert _AGENTPACK_MARKER in content
            assert "GitAutoRepack" in content
            assert "agentpack.cli" in content

    def test_hooks_are_executable(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        install_git_template_hooks()
        for name in _HOOK_SCRIPTS:
            hook = tmp_path / ".git-templates" / "hooks" / name
            assert hook.stat().st_mode & stat.S_IXUSR

    def test_idempotent(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        install_git_template_hooks()
        results2 = install_git_template_hooks()
        assert all(v == "unchanged" for v in results2.values())

    def test_appends_to_existing_hook(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        hooks_dir = tmp_path / ".git-templates" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / "post-commit"
        hook.write_text("#!/bin/sh\necho 'existing'\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        results = install_git_template_hooks()
        assert results["post-commit"] == "appended"
        content = hook.read_text()
        assert "existing" in content
        assert _AGENTPACK_MARKER in content

    def test_remove_cleans_hooks(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        install_git_template_hooks()
        remove_git_template_hooks()
        for name in _HOOK_SCRIPTS:
            hook = tmp_path / ".git-templates" / "hooks" / name
            assert not hook.exists() or _AGENTPACK_MARKER not in hook.read_text()

    def test_remove_preserves_other_content(self, tmp_path, monkeypatch):
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        hooks_dir = tmp_path / ".git-templates" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / "post-commit"
        hook.write_text("#!/bin/sh\necho 'keep me'\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        install_git_template_hooks()
        remove_git_template_hooks()
        assert hook.exists()
        assert "keep me" in hook.read_text()
        assert _AGENTPACK_MARKER not in hook.read_text()


# ---------------------------------------------------------------------------
# Shell hook
# ---------------------------------------------------------------------------

class TestShellHook:
    def test_creates_zshrc_hook(self, tmp_path):
        rc = tmp_path / ".zshrc"
        action, path = install_shell_hook(rc)
        assert action in ("created", "appended")
        assert path == rc
        content = rc.read_text()
        assert _SHELL_MARKER_START in content
        assert _SHELL_MARKER_END in content
        assert "_agentpack_chpwd" in content

    def test_idempotent(self, tmp_path):
        rc = tmp_path / ".zshrc"
        install_shell_hook(rc)
        action2, _ = install_shell_hook(rc)
        assert action2 == "unchanged"
        # Ensure no duplication
        content = rc.read_text()
        assert content.count(_SHELL_MARKER_START) == 1

    def test_appends_to_existing_zshrc(self, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text("# My existing zsh config\nexport PATH=$PATH:/usr/local/bin\n")
        action, _ = install_shell_hook(rc)
        assert action == "appended"
        content = rc.read_text()
        assert "My existing zsh config" in content
        assert _SHELL_MARKER_START in content

    def test_updates_stale_hook(self, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text(f"# stuff\n{_SHELL_MARKER_START}\nold content\n{_SHELL_MARKER_END}\n# more stuff\n")
        action, _ = install_shell_hook(rc)
        assert action == "updated"
        content = rc.read_text()
        assert "old content" not in content
        assert "_agentpack_chpwd" in content
        assert "# stuff" in content
        assert "# more stuff" in content

    def test_remove_shell_hook(self, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text("# existing\n")
        install_shell_hook(rc)
        action, _ = remove_shell_hook(rc)
        assert action == "removed"
        content = rc.read_text()
        assert _SHELL_MARKER_START not in content
        assert "# existing" in content

    def test_remove_noop_if_not_installed(self, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text("# nothing here\n")
        action, _ = remove_shell_hook(rc)
        assert action == "unchanged"

    def test_shell_hook_guards_on_config_toml(self, tmp_path):
        """Hook must only act on repos with .agentpack/config.toml — never auto-init unknown repos."""
        rc = tmp_path / ".zshrc"
        install_shell_hook(rc)
        content = rc.read_text()
        assert ".agentpack/config.toml" in content
        # The executable body must check config.toml before doing anything
        # (comment lines referencing 'agentpack init' are acceptable)
        body_lines = [
            line for line in content.splitlines()
            if not line.strip().startswith("#") and "agentpack init" in line
        ]
        assert body_lines == [], f"Shell hook body auto-inits without opt-in check: {body_lines}"

    def test_git_hooks_guard_on_config_toml(self, tmp_path):
        """Git template hooks must delegate opt-in checks to the Python hook runner."""
        import agentpack.integrations.global_install as gi
        gi._GIT_TEMPLATE_DIR = tmp_path / ".git-templates"
        install_git_template_hooks()
        for name in _HOOK_SCRIPTS:
            content = (tmp_path / ".git-templates" / "hooks" / name).read_text()
            assert "GitAutoRepack" in content
            assert ".agentpack/config.toml" not in content

    def test_detect_rc_file_prefers_powershell_on_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agentpack.integrations.global_install.is_windows", lambda: True)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        path = _detect_rc_file()

        assert path == tmp_path / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"

    def test_install_shell_hook_writes_powershell_profile(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agentpack.integrations.global_install.is_windows", lambda: True)
        profile = tmp_path / "Microsoft.PowerShell_profile.ps1"

        action, path = install_shell_hook(profile)

        assert action in ("created", "appended")
        assert path == profile
        content = profile.read_text()
        assert "Invoke-AgentPackChpwd" in content
        assert "Start-Process -WindowStyle Hidden" in content
        assert ".agentpack/config.toml" in content


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:
    def test_skips_if_already_initialized(self, tmp_path):
        from agentpack.core.bootstrap import is_initialized, bootstrap_if_needed
        (tmp_path / ".git").mkdir()
        (tmp_path / ".agentpack").mkdir()
        (tmp_path / ".agentpack" / "config.toml").write_text("[project]\n")
        assert is_initialized(tmp_path)
        result = bootstrap_if_needed(tmp_path)
        assert result is False

    def test_skips_if_no_git_dir(self, tmp_path):
        from agentpack.core.bootstrap import bootstrap_if_needed
        result = bootstrap_if_needed(tmp_path)
        assert result is False

    def test_is_initialized_false_for_fresh_dir(self, tmp_path):
        from agentpack.core.bootstrap import is_initialized
        assert not is_initialized(tmp_path)
