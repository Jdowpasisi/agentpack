import json

from agentpack.integrations.vscode_tasks import install_vscode_tasks, remove_vscode_tasks


class TestInstallVscodeTasks:
    def test_creates_tasks_json(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="cursor")
        tasks_path = tmp_path / ".vscode" / "tasks.json"
        assert tasks_path.exists()
        data = json.loads(tasks_path.read_text())
        assert data["version"] == "2.0.0"
        labels = [t["label"] for t in data["tasks"]]
        assert "AgentPack: Repack context" in labels
        assert "AgentPack: Repack (auto task)" in labels
        assert "AgentPack: Guard context" in labels

    def test_agent_name_in_command(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="windsurf")
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        commands = [t["command"] for t in data["tasks"]]
        assert all("windsurf" in cmd for cmd in commands)

    def test_idempotent(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="cursor")
        first = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        install_vscode_tasks(tmp_path, agent="cursor")
        second = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        assert len(first["tasks"]) == len(second["tasks"])

    def test_preserves_existing_tasks(self, tmp_path):
        (tmp_path / ".vscode").mkdir()
        existing = {
            "version": "2.0.0",
            "tasks": [{"label": "Build", "type": "shell", "command": "make build"}],
        }
        (tmp_path / ".vscode" / "tasks.json").write_text(json.dumps(existing))
        install_vscode_tasks(tmp_path, agent="cursor")
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        labels = [t["label"] for t in data["tasks"]]
        assert "Build" in labels
        assert "AgentPack: Repack context" in labels

    def test_updates_stale_agent(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="cursor")
        install_vscode_tasks(tmp_path, agent="windsurf")
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        commands = [t["command"] for t in data["tasks"] if "AgentPack" in t["label"]]
        assert all("windsurf" in cmd for cmd in commands)
        assert all("cursor" not in cmd for cmd in commands)

    def test_auto_task_has_folder_open_trigger(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="cursor")
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        auto_task = next(t for t in data["tasks"] if t["label"] == "AgentPack: Repack (auto task)")
        assert auto_task["runOptions"]["runOn"] == "folderOpen"
        assert "agentpack guard" in auto_task["command"]
        assert "--repair-stale" in auto_task["command"]


class TestRemoveVscodeTasks:
    def test_removes_agentpack_tasks(self, tmp_path):
        install_vscode_tasks(tmp_path, agent="cursor")
        remove_vscode_tasks(tmp_path)
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        assert all("AgentPack" not in t["label"] for t in data["tasks"])

    def test_preserves_other_tasks(self, tmp_path):
        (tmp_path / ".vscode").mkdir()
        existing = {
            "version": "2.0.0",
            "tasks": [{"label": "Build", "type": "shell", "command": "make build"}],
        }
        (tmp_path / ".vscode" / "tasks.json").write_text(json.dumps(existing))
        install_vscode_tasks(tmp_path, agent="cursor")
        remove_vscode_tasks(tmp_path)
        data = json.loads((tmp_path / ".vscode" / "tasks.json").read_text())
        assert any(t["label"] == "Build" for t in data["tasks"])

    def test_noop_if_not_installed(self, tmp_path):
        action = remove_vscode_tasks(tmp_path)
        assert action == "unchanged"
