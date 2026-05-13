from agentpack.adapters.antigravity import AntigravityAdapter


class TestAntigravityAdapter:
    def test_patch_gemini_md_creates_task_switch_protocol(self, tmp_path):
        adapter = AntigravityAdapter()
        action = adapter.patch_gemini_md(tmp_path)

        assert action == "created"
        content = (tmp_path / "GEMINI.md").read_text()
        assert "skills:" in content
        assert "agentpack pack --task auto" in content
        assert ".agent/skills/agentpack/SKILL.md" in content
        assert "When the user switches to a different coding task" in content

    def test_patch_gemini_md_idempotent(self, tmp_path):
        adapter = AntigravityAdapter()
        adapter.patch_gemini_md(tmp_path)
        action2 = adapter.patch_gemini_md(tmp_path)
        assert action2 == "unchanged"
