import json

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

    def test_patch_codex_hooks_creates_lifecycle_hooks(self, tmp_path):
        adapter = CodexAdapter()
        action = adapter.patch_codex_hooks(tmp_path)

        assert action == "created"
        hooks_path = tmp_path / ".codex" / "hooks.json"
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        assert "agentpack hook --event SessionStart" in json.dumps(data)
        assert "agentpack hook --event UserPromptSubmit" in json.dumps(data)

    def test_patch_codex_hooks_idempotent(self, tmp_path):
        adapter = CodexAdapter()
        adapter.patch_codex_hooks(tmp_path)
        action2 = adapter.patch_codex_hooks(tmp_path)

        assert action2 == "unchanged"

    def test_patch_codex_hooks_preserves_existing_hooks(self, tmp_path):
        hooks_path = tmp_path / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]}}),
            encoding="utf-8",
        )

        adapter = CodexAdapter()
        action = adapter.patch_codex_hooks(tmp_path)

        assert action == "updated"
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo done"
        assert "agentpack hook --event UserPromptSubmit" in json.dumps(data)

    def test_output_path(self, tmp_path):
        adapter = CodexAdapter()
        assert adapter.output_path(tmp_path) == tmp_path / ".agentpack" / "context.md"
