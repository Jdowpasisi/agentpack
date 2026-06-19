from agentpack.adapters.antigravity import AntigravityAdapter


class TestAntigravityAdapter:
    def test_patch_gemini_md_creates_task_switch_protocol(self, tmp_path):
        adapter = AntigravityAdapter()
        action = adapter.patch_gemini_md(tmp_path)

        assert action == "created"
        content = (tmp_path / "GEMINI.md").read_text()
        assert "skills:" in content
        assert "agentpack_readiness()" in content
        assert "agentpack_get_context()" in content
        assert "agentpack_pack_context" in content
        assert "agentpack guard --agent antigravity --repair-stale --refresh-context" in content
        assert "MCP is the active path" in content
        assert "agentpack:freshness" in content
        assert ".agent/skills/agentpack/SKILL.md" in content
        assert "When the user switches to a different coding task" in content

    def test_patch_gemini_md_idempotent(self, tmp_path):
        adapter = AntigravityAdapter()
        adapter.patch_gemini_md(tmp_path)
        action2 = adapter.patch_gemini_md(tmp_path)
        assert action2 == "unchanged"
