from __future__ import annotations

import json

from typer.testing import CliRunner

from agentpack.cli import app


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


def test_skills_scan_prints_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_route_fixture(tmp_path)

    result = CliRunner().invoke(app, ["skills", "scan"])

    assert result.exit_code == 0, result.output
    assert "Found 1 skills and 1 rules" in result.output
    assert "django-pytest" in result.output


def test_skills_index_writes_valid_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_route_fixture(tmp_path)

    result = CliRunner().invoke(app, ["skills", "index"])

    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / ".agentpack" / "skills_index.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["inventory"]["version"] == 1
    assert data["inventory"]["skills"][0]["name"] == "django-pytest"
    assert data["inventory"]["rules"][0]["path"] == "AGENTS.md"
    assert data["configured_paths"] == [".agentpack/skills", ".cursor/rules"]
    assert data["sources"]
    assert "raw_text" not in data["inventory"]["skills"][0]
    assert "raw_text" not in data["inventory"]["rules"][0]


def test_skills_recommend_explain_prints_skill_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_route_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        ["skills", "recommend", "--task", "fix flaky payment webhook test", "--explain"],
    )

    assert result.exit_code == 0, result.output
    assert "Recommended skills" in result.output
    assert "django-pytest" in result.output
    assert "confidence" in result.output
    assert "Skill Plan" in result.output


def test_skills_feedback_records_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    result = CliRunner().invoke(
        app,
        [
            "skills",
            "feedback",
            "--task",
            "fix auth",
            "--used-skill",
            "auth-review",
            "--changed-file",
            "src/auth.py",
            "--tests-passed",
            "--user-feedback",
            "helpful",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / ".agentpack" / "skill_feedback.jsonl").read_text(encoding="utf-8"))
    assert data["task"] == "fix auth"
    assert data["used_skills"] == ["auth-review"]
    assert data["changed_files"] == ["src/auth.py"]
    assert data["tests_passed"] is True


def test_route_json_returns_stable_keys_and_does_not_write_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_route_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        ["route", "--task", "fix flaky payment webhook test", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) >= {
        "task",
        "task_mode",
        "task_mode_confidence",
        "task_mode_signals",
        "selected_files",
        "selected_skills",
        "applied_rules",
        "suggested_commands",
        "evidence_checklist",
        "routing_notes",
        "safety_warnings",
        "agent_prompt",
    }
    assert data["selected_files"]
    assert data["selected_skills"][0]["skill"]["name"] == "django-pytest"
    assert data["applied_rules"][0]["rule"]["path"] == "AGENTS.md"
    assert "pytest" in data["suggested_commands"][0]["command"]
    assert data["task_mode"] in {"small_direct_edit", "broad_feature"}
    assert data["task_mode_confidence"] > 0
    assert not (tmp_path / ".agentpack" / "context.md").exists()
    assert not (tmp_path / ".agentpack" / "context.claude.md").exists()


def test_route_refreshes_stale_skills_index(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_route_fixture(tmp_path)
    runner = CliRunner()

    index = runner.invoke(app, ["skills", "index"])
    assert index.exit_code == 0, index.output

    skill = tmp_path / ".agentpack" / "skills" / "django-pytest" / "SKILL.md"
    skill.write_text(
        "# django-pytest\n\nUse for pytest test debugging, fixtures, mocks, flaky tests, and regression tests.\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["route", "--task", "fix pytest regression", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = [item["skill"]["name"] for item in payload["selected_skills"]]
    assert "django-pytest" in names


def test_route_small_direct_edit_recommends_targeted_search(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Button.tsx").write_text("export function Button(){ return null }\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["route", "--task", "small css fix Button.tsx", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["task_mode"] == "small_direct_edit"
    assert any("targeted `rg`" in note for note in data["routing_notes"])
    assert data["evidence_checklist"]


def test_route_runtime_debugging_returns_evidence_checklist(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "customerio_events.py").write_text("def send_event(row): return row\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["route", "--task", "debug Customer.io event pipeline logs", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["task_mode"] == "runtime_debugging"
    assert "inspect runtime/tool evidence for the exact failing session" in data["evidence_checklist"]


def test_route_pr_review_suppresses_noisy_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): return True\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".agentpack/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "src" / "auth.py").write_text("def login(): return False\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".agentpack/\ndist/\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["route", "--task", "review PR auth diff", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    paths = [item["path"] for item in data["selected_files"]]
    assert data["task_mode"] == "pr_review"
    assert paths[0] == "src/auth.py"
    assert ".gitignore" not in paths


def test_route_pr_review_keeps_changed_workflow_diff_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "deploy.yml").write_text("name: deploy\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# deployment workflow helper\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / ".github" / "workflows" / "deploy.yml").write_text(
        "name: deploy\non: push\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["route", "--task", "review PR deployment workflow", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    paths = [item["path"] for item in data["selected_files"]]
    assert data["task_mode"] == "pr_review"
    assert paths[0] == ".github/workflows/deploy.yml"


def test_route_pr_review_can_prioritize_github_pr_files(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "customerio_events.py").write_text("def send(): return True\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "noise.md").write_text("review diff notes\n", encoding="utf-8")

    class Result:
        returncode = 0
        stdout = "backend/customerio_events.py\n"
        stderr = ""

    monkeypatch.setattr("agentpack.router.service.shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr("agentpack.router.service.subprocess.run", lambda *args, **kwargs: Result())

    result = CliRunner().invoke(app, ["route", "--task", "review PR #123 for Customer.io events", "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    paths = [item["path"] for item in data["selected_files"]]
    assert data["task_mode"] == "pr_review"
    assert data["task_mode_confidence"] >= 0.68
    assert any("pr-review" in signal for signal in data["task_mode_signals"])
    assert paths[0] == "backend/customerio_events.py"
    assert "GitHub PR file" in data["selected_files"][0]["reasons"]
