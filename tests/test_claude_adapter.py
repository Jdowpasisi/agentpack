import pytest
from pathlib import Path
from agentpack.adapters.claude import ClaudeAdapter, _AGENTPACK_BLOCK, _BLOCK_RE
from agentpack.core.models import ContextPack


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
