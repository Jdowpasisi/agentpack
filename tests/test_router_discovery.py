from __future__ import annotations

from agentpack.router.discovery import discover_inventory


def test_discovery_finds_repo_global_cursor_and_agent_rules(tmp_path, monkeypatch):
    repo_skill = tmp_path / ".agentpack" / "skills" / "webhook" / "SKILL.md"
    repo_skill.parent.mkdir(parents=True)
    repo_skill.write_text("# Webhook Idempotency\n\nUse for webhook handlers.\n", encoding="utf-8")

    home = tmp_path / "home"
    global_skill = home / ".codex" / "skills" / "django-pytest" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    global_skill.write_text("# Django Pytest\n\nUse for pytest workflows.\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    cursor_rule = tmp_path / ".cursor" / "rules" / "tests.mdc"
    cursor_rule.parent.mkdir(parents=True)
    cursor_rule.write_text(
        "---\ndescription: Test rule\nglobs: tests/**\n---\n\nUse test rules.\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("# Repo Rules\n\nFollow repo instructions.\n", encoding="utf-8")

    inventory = discover_inventory(tmp_path)

    assert {skill.name for skill in inventory.skills} >= {"Webhook Idempotency", "Django Pytest"}
    assert {rule.path for rule in inventory.rules} >= {".cursor/rules/tests.mdc", "AGENTS.md"}


def test_discovery_ignores_missing_directories(tmp_path):
    inventory = discover_inventory(tmp_path, paths=[".missing", "~/.also-missing"])

    assert inventory.skills == []
    assert inventory.rules == []
