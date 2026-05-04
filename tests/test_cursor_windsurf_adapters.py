import json
import tempfile
from pathlib import Path

import pytest

from agentpack.adapters.cursor import CursorAdapter
from agentpack.adapters.windsurf import WindsurfAdapter


# ---------------------------------------------------------------------------
# CursorAdapter
# ---------------------------------------------------------------------------

class TestCursorAdapter:
    def test_patch_cursor_rules_creates(self, tmp_path):
        adapter = CursorAdapter()
        action = adapter.patch_cursor_rules(tmp_path)
        assert action == "created"
        content = (tmp_path / ".cursorrules").read_text()
        assert "agentpack:rule:start" in content
        assert "agentpack session refresh" in content

    def test_patch_cursor_rules_idempotent(self, tmp_path):
        adapter = CursorAdapter()
        adapter.patch_cursor_rules(tmp_path)
        action2 = adapter.patch_cursor_rules(tmp_path)
        assert action2 == "unchanged"

    def test_patch_cursor_rules_appends_to_existing(self, tmp_path):
        rules = tmp_path / ".cursorrules"
        rules.write_text("# My existing rules\nAlways use TypeScript.\n")
        adapter = CursorAdapter()
        action = adapter.patch_cursor_rules(tmp_path)
        assert action == "appended"
        content = rules.read_text()
        assert "My existing rules" in content
        assert "agentpack:rule:start" in content

    def test_patch_cursor_rules_updates_stale_block(self, tmp_path):
        rules = tmp_path / ".cursorrules"
        rules.write_text("<!-- agentpack:rule:start -->\nOld text\n<!-- agentpack:rule:end -->\n")
        adapter = CursorAdapter()
        action = adapter.patch_cursor_rules(tmp_path)
        assert action == "updated"
        content = rules.read_text()
        assert "Old text" not in content
        assert "agentpack session refresh" in content

    def test_patch_cursor_mdc_creates(self, tmp_path):
        adapter = CursorAdapter()
        action = adapter.patch_cursor_mdc(tmp_path)
        assert action in ("created", "updated")
        mdc = tmp_path / ".cursor" / "rules" / "agentpack.mdc"
        assert mdc.exists()
        content = mdc.read_text()
        assert "alwaysApply: true" in content
        assert "agentpack session refresh" in content

    def test_patch_cursor_mdc_idempotent(self, tmp_path):
        adapter = CursorAdapter()
        adapter.patch_cursor_mdc(tmp_path)
        action2 = adapter.patch_cursor_mdc(tmp_path)
        assert action2 == "unchanged"

    def test_output_path(self, tmp_path):
        adapter = CursorAdapter()
        assert adapter.output_path(tmp_path) == tmp_path / ".agentpack" / "context.md"


# ---------------------------------------------------------------------------
# WindsurfAdapter
# ---------------------------------------------------------------------------

class TestWindsurfAdapter:
    def test_patch_windsurfrules_creates(self, tmp_path):
        adapter = WindsurfAdapter()
        action = adapter.patch_windsurfrules(tmp_path)
        assert action == "created"
        content = (tmp_path / ".windsurfrules").read_text()
        assert "agentpack:rule:start" in content
        assert "agentpack session refresh" in content

    def test_patch_windsurfrules_idempotent(self, tmp_path):
        adapter = WindsurfAdapter()
        adapter.patch_windsurfrules(tmp_path)
        action2 = adapter.patch_windsurfrules(tmp_path)
        assert action2 == "unchanged"

    def test_patch_windsurfrules_appends_to_existing(self, tmp_path):
        rules = tmp_path / ".windsurfrules"
        rules.write_text("# My existing rules\nAlways write tests.\n")
        adapter = WindsurfAdapter()
        action = adapter.patch_windsurfrules(tmp_path)
        assert action == "appended"
        content = rules.read_text()
        assert "My existing rules" in content
        assert "agentpack:rule:start" in content

    def test_patch_windsurfrules_updates_stale_block(self, tmp_path):
        rules = tmp_path / ".windsurfrules"
        rules.write_text("<!-- agentpack:rule:start -->\nOld text\n<!-- agentpack:rule:end -->\n")
        adapter = WindsurfAdapter()
        action = adapter.patch_windsurfrules(tmp_path)
        assert action == "updated"
        content = rules.read_text()
        assert "Old text" not in content
        assert "agentpack session refresh" in content

    def test_output_path(self, tmp_path):
        adapter = WindsurfAdapter()
        assert adapter.output_path(tmp_path) == tmp_path / ".agentpack" / "context.md"


# ---------------------------------------------------------------------------
# install command smoke test
# ---------------------------------------------------------------------------

class TestInstallCommand:
    def test_cursor_install_creates_rules_and_mdc(self, tmp_path, monkeypatch):
        from agentpack.adapters.cursor import CursorAdapter
        adapter = CursorAdapter()
        adapter.patch_cursor_rules(tmp_path)
        adapter.patch_cursor_mdc(tmp_path)
        assert (tmp_path / ".cursorrules").exists()
        assert (tmp_path / ".cursor" / "rules" / "agentpack.mdc").exists()

    def test_windsurf_install_creates_rules(self, tmp_path):
        from agentpack.adapters.windsurf import WindsurfAdapter
        adapter = WindsurfAdapter()
        adapter.patch_windsurfrules(tmp_path)
        assert (tmp_path / ".windsurfrules").exists()
