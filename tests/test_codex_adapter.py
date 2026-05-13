from agentpack.adapters.codex import CodexAdapter


class TestCodexAdapter:
    def test_patch_agents_md_creates(self, tmp_path):
        adapter = CodexAdapter()
        action = adapter.patch_agents_md(tmp_path)
        assert action == "created"
        content = (tmp_path / "AGENTS.md").read_text()
        assert "agentpack:start" in content
        assert "agentpack pack --task auto" in content
        assert ".agentpack/task.md" in content
        assert ".agentpack/context.md" in content
        assert "When the user switches to a different coding task" in content

    def test_patch_agents_md_idempotent(self, tmp_path):
        adapter = CodexAdapter()
        adapter.patch_agents_md(tmp_path)
        action2 = adapter.patch_agents_md(tmp_path)
        assert action2 == "unchanged"

    def test_patch_agents_md_appends_to_existing(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# My project\nAlways run tests before committing.\n")
        adapter = CodexAdapter()
        action = adapter.patch_agents_md(tmp_path)
        assert action == "appended"
        content = agents_md.read_text()
        assert "My project" in content
        assert "agentpack:start" in content

    def test_patch_agents_md_updates_stale_block(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("<!-- agentpack:start -->\nOld text\n<!-- agentpack:end -->\n")
        adapter = CodexAdapter()
        action = adapter.patch_agents_md(tmp_path)
        assert action == "updated"
        content = agents_md.read_text()
        assert "Old text" not in content
        assert "agentpack pack --task auto" in content

    def test_output_path(self, tmp_path):
        adapter = CodexAdapter()
        assert adapter.output_path(tmp_path) == tmp_path / ".agentpack" / "context.md"
