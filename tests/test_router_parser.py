from __future__ import annotations

from agentpack.router.parser import parse_rule_file, parse_skill_file


def test_parse_skill_frontmatter_name_description(tmp_path):
    skill_dir = tmp_path / ".codex" / "skills" / "django-pytest"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        "name: django-pytest\n"
        "description: Use for Django test debugging and pytest workflows.\n"
        "---\n\n"
        "## When to use\n"
        "Use this when debugging pytest fixtures, mocks, and flaky Django tests.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "django-pytest"
    assert skill.description == "Use for Django test debugging and pytest workflows."
    assert "pytest" in skill.triggers
    assert "pytest" in skill.tools_required
    assert skill.side_effect_level == "command"


def test_parse_karpathy_skill_frontmatter(tmp_path):
    path = tmp_path / "skills" / "karpathy-guidelines" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: karpathy-guidelines\n"
        "description: Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.\n"
        "license: MIT\n"
        "---\n\n"
        "# Karpathy Guidelines\n\n"
        "Behavioral guidelines to reduce common LLM coding mistakes.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "karpathy-guidelines"
    assert "refactoring" in skill.triggers
    assert skill.side_effect_level == "none"


def test_parse_skill_h1_fallback_and_dangerous_external(tmp_path):
    path = tmp_path / ".agentpack" / "skills" / "deploy" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Production Deploy\n\n"
        "Deploy to cloud, migrate the database, and send Slack updates.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "Production Deploy"
    assert skill.side_effect_level == "external"


def test_parse_cursor_mdc_rule_frontmatter(tmp_path):
    path = tmp_path / ".cursor" / "rules" / "tests.mdc"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "description: Test rules\n"
        "globs: tests/**, */tests/**\n"
        "---\n\n"
        "Always write focused tests.\n",
        encoding="utf-8",
    )

    rule = parse_rule_file(path, root=tmp_path, source=".cursor/rules", priority=60)

    assert rule.name == "tests.mdc"
    assert rule.description == "Test rules"
    assert rule.scope_paths == ["tests/**", "*/tests/**"]
    assert rule.priority == 60
