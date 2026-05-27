from __future__ import annotations

from agentpack.core.execution_state import build_execution_state, parse_task_state


def test_parse_task_state_extracts_status_summary_and_checklist() -> None:
    state = parse_task_state(
        "Status: in_progress\n"
        "Summary: Budget work done.\n\n"
        "- [x] rendered budget\n"
        "- [ ] execution state\n"
        "- [!] conflict warning\n"
    )

    assert state["status"] == "in_progress"
    assert state["summary"] == "Budget work done."
    assert state["checklist"] == {"done": 1, "open": 1, "blocked": 1}


def test_build_execution_state_reads_task_state_and_runtime_missing_docker(tmp_path, monkeypatch) -> None:
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "task_state.md").write_text(
        "Status: blocked\nSummary: Waiting for review.\n- [!] reviewer needed\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agentpack.core.execution_state.shutil.which", lambda name: None)

    state = build_execution_state(tmp_path)

    assert state["task"]["status"] == "blocked"
    assert state["task"]["summary"] == "Waiting for review."
    assert state["runtime"]["docker"] == "missing"


def test_build_execution_state_reports_docker_running(tmp_path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "25.0.0\n"
        stderr = ""

    monkeypatch.setattr("agentpack.core.execution_state.shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr("agentpack.core.execution_state.subprocess.run", lambda *args, **kwargs: Result())

    state = build_execution_state(tmp_path)

    assert state["runtime"]["docker"] == "running"
    assert state["runtime"]["detail"] == "25.0.0"
