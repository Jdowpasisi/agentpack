from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.mcp_runtime import check_mcp_runtime


def test_mcp_runtime_reports_missing_extra(monkeypatch, tmp_path) -> None:
    def fake_import(name: str):
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr("agentpack.core.mcp_runtime.shutil.which", lambda command: "/bin/agentpack")
    monkeypatch.setattr("agentpack.core.mcp_runtime.importlib.import_module", fake_import)

    result = check_mcp_runtime(root=tmp_path)

    assert result.status == "missing_extra"
    assert not result.ok
    assert 'pipx inject agentpack-cli "agentpack-cli[mcp]"' in result.remediation


def test_mcp_runtime_reports_stdio_waiting_and_kills_process(monkeypatch, tmp_path) -> None:
    class FakeProc:
        returncode = None
        killed = False

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["agentpack", "mcp"], timeout)

        def communicate(self):
            return "", ""

        def kill(self):
            self.killed = True

    proc = FakeProc()
    monkeypatch.setattr("agentpack.core.mcp_runtime.shutil.which", lambda command: "/bin/agentpack")
    monkeypatch.setattr("agentpack.core.mcp_runtime.importlib.import_module", lambda name: object())
    monkeypatch.setattr("agentpack.core.mcp_runtime.subprocess.Popen", lambda *args, **kwargs: proc)

    result = check_mcp_runtime(root=tmp_path, timeout_s=0.01)

    assert result.status == "stdio_waiting"
    assert result.ok
    assert proc.killed is True


def test_mcp_command_help_marks_server_debug_entrypoint() -> None:
    result = CliRunner().invoke(app, ["mcp", "--help"])

    assert result.exit_code == 0, result.output
    assert "stdio MCP server" in result.output
    assert "bounded" in result.output
    assert "diagnostic" in result.output
