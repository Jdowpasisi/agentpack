import json

from agentpack.adapters.claude import ClaudeAdapter
from agentpack.core.models import ContextPack
from agentpack.installers.claude import ClaudeInstaller


def _empty_pack() -> ContextPack:
    return ContextPack(
        task="fix bug",
        agent="claude",
        mode="balanced",
        budget=25000,
        token_estimate=1000,
        raw_repo_tokens=100000,
        after_ignore_tokens=20000,
        estimated_savings_percent=95.0,
        changed_files=[],
        selected_files=[],
        receipts=[],
    )


def test_render_contains_task():
    adapter = ClaudeAdapter()
    text = adapter.render(_empty_pack())
    assert "fix bug" in text


def test_render_contains_stats():
    adapter = ClaudeAdapter()
    text = adapter.render(_empty_pack())
    assert "Token Stats" in text
    assert "95.0%" in text


def test_patch_creates_claude_md(tmp_path):
    adapter = ClaudeAdapter()
    action = adapter.patch_claude_md(tmp_path)
    assert action == "created"
    assert (tmp_path / "CLAUDE.md").exists()
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "agentpack:start" in content


def test_patch_appends_to_existing(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# My project\n\nExisting content.\n")
    adapter = ClaudeAdapter()
    action = adapter.patch_claude_md(tmp_path)
    assert action == "appended"
    content = claude_md.read_text()
    assert "My project" in content
    assert "agentpack:start" in content


def test_patch_updates_existing_block(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Project\n\n<!-- agentpack:start -->\nOld content\n<!-- agentpack:end -->\n")
    adapter = ClaudeAdapter()
    action = adapter.patch_claude_md(tmp_path)
    assert action in ("updated", "unchanged")
    content = claude_md.read_text()
    assert "# Project" in content
    assert "Old content" not in content


def test_patch_idempotent(tmp_path):
    adapter = ClaudeAdapter()
    adapter.patch_claude_md(tmp_path)
    content1 = (tmp_path / "CLAUDE.md").read_text()
    adapter.patch_claude_md(tmp_path)
    content2 = (tmp_path / "CLAUDE.md").read_text()
    assert content1 == content2


# ---------------------------------------------------------------------------
# ClaudeInstaller.patch_mcp_server
# ---------------------------------------------------------------------------

class TestPatchMcpServer:
    _entry = {"command": "agentpack", "args": ["mcp"]}

    def test_local_creates_mcp_json(self, tmp_path):
        installer = ClaudeInstaller()
        action = installer.patch_mcp_server(tmp_path, global_install=False)
        assert action == "updated"
        mcp_json = tmp_path / ".mcp.json"
        assert mcp_json.exists()
        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["agentpack"] == self._entry

    def test_local_idempotent(self, tmp_path):
        installer = ClaudeInstaller()
        installer.patch_mcp_server(tmp_path, global_install=False)
        action2 = installer.patch_mcp_server(tmp_path, global_install=False)
        assert action2 == "unchanged"

    def test_local_does_not_write_claude_settings(self, tmp_path):
        installer = ClaudeInstaller()
        installer.patch_mcp_server(tmp_path, global_install=False)
        claude_settings = tmp_path / ".claude" / "settings.json"
        assert not claude_settings.exists()

    def test_local_migrates_stale_mcp_from_claude_settings(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({"hooks": {}, "mcpServers": {"agentpack": self._entry}}) + "\n")

        installer = ClaudeInstaller()
        installer.patch_mcp_server(tmp_path, global_install=False)

        remaining = json.loads(settings.read_text())
        assert "mcpServers" not in remaining
        assert "hooks" in remaining

    def test_local_preserves_existing_mcp_json_entries(self, tmp_path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}}}) + "\n")
        installer = ClaudeInstaller()
        installer.patch_mcp_server(tmp_path, global_install=False)
        data = json.loads(mcp_json.read_text())
        assert "other" in data["mcpServers"]
        assert "agentpack" in data["mcpServers"]

    def test_global_writes_claude_settings(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)
        installer = ClaudeInstaller()
        action = installer.patch_mcp_server(tmp_path, global_install=True)
        assert action == "updated"
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        assert data["mcpServers"]["agentpack"] == self._entry

    def test_global_does_not_create_mcp_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        (tmp_path / ".claude").mkdir(parents=True)
        installer = ClaudeInstaller()
        installer.patch_mcp_server(tmp_path, global_install=True)
        assert not (tmp_path / ".mcp.json").exists()
