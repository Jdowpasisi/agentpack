from __future__ import annotations

import json
import sys
import types

import pytest

from agentpack.mcp_server import _explain_route_impl, _get_skills_impl, _route_task_impl, serve


def _write_route_fixture(root):
    (root / ".agentpack").mkdir(exist_ok=True)
    (root / ".agentpack" / "config.toml").write_text(
        "[skills]\npaths = [\".agentpack/skills\", \".cursor/rules\"]\n",
        encoding="utf-8",
    )
    (root / "payments").mkdir()
    (root / "payments" / "webhooks.py").write_text("def handle_webhook(event):\n    return event\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_payment_webhooks.py").write_text(
        "from payments.webhooks import handle_webhook\n\n"
        "def test_payment_webhook():\n"
        "    assert handle_webhook({'id': 'evt_1'})\n",
        encoding="utf-8",
    )
    skill = root / ".agentpack" / "skills" / "django-pytest" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "# django-pytest\n\nUse for pytest test debugging, fixtures, mocks, and flaky tests.\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Repo Rules\n\nVerify changes with tests.\n", encoding="utf-8")


def test_mcp_route_task_returns_json_and_does_not_write_context(tmp_path):
    _write_route_fixture(tmp_path)

    data = json.loads(_route_task_impl(tmp_path, "fix flaky payment webhook test"))

    assert data["selected_files"]
    assert data["selected_skills"][0]["skill"]["name"] == "django-pytest"
    assert data["applied_rules"][0]["rule"]["path"] == "AGENTS.md"
    assert "agent_prompt" in data
    assert not (tmp_path / ".agentpack" / "task.md").exists()
    assert not (tmp_path / ".agentpack" / "context.md").exists()


def test_mcp_get_skills_returns_inventory_json(tmp_path):
    _write_route_fixture(tmp_path)

    data = json.loads(_get_skills_impl(tmp_path))

    assert data["skills"][0]["name"] == "django-pytest"
    assert data["rules"][0]["path"] == "AGENTS.md"


def test_mcp_explain_route_includes_skill_scores(tmp_path):
    _write_route_fixture(tmp_path)

    data = json.loads(_explain_route_impl(tmp_path, "fix flaky payment webhook test"))

    assert data["skill_scores"]
    assert data["skill_scores"][0]["reasons"]


def test_mcp_server_registers_router_tools(monkeypatch):
    class FakeMCP:
        instances = []

        def __init__(self, name):
            self.name = name
            self.tools = {}
            FakeMCP.instances.append(self)

        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

        def run(self):
            raise RuntimeError("stop after registration")

    fake_module = types.ModuleType("mcp.server.fastmcp")
    fake_module.FastMCP = FakeMCP
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_module)

    with pytest.raises(RuntimeError, match="stop after registration"):
        serve()

    tool_names = set(FakeMCP.instances[0].tools)
    assert {"route_task", "get_skills", "explain_route"} <= tool_names
