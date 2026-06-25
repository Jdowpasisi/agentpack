from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.commands.review_cmd import _build_review_preflight, _load_review_template, _review_output_paths


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_foo.py").write_text("def test_foo():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

    subprocess.run(["git", "checkout", "-b", "feature/review"], cwd=tmp_path, check=True)
    (tmp_path / "src" / "foo.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/foo.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "change foo"], cwd=tmp_path, check=True)
    return tmp_path


def test_build_review_preflight_uses_pr_base_and_related_tests(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(
        "agentpack.commands.review_cmd._gh_pr_metadata",
        lambda _root: {
            "number": 6,
            "title": "Review flow",
            "url": "https://example.com/pr/6",
            "base_ref": "main",
            "head_ref": "feature/review",
        },
    )

    outputs = _review_output_paths(repo)
    preflight = _build_review_preflight(repo, "focus on backward compatibility", outputs)

    assert preflight["review_context"] == "focus on backward compatibility"
    assert preflight["review"]["mode"] == "fresh"
    assert preflight["review"]["branch_prefix"] == "feature-review"
    assert preflight["execution_contract"] == {
        "structured_format": "TOON",
        "requires_write_to_file": True,
        "requires_read_file_between_stages": True,
        "forbid_inline_review": True,
        "blocked_without_stage_artifact": True,
        "stage_order": ["understanding", "judge"],
    }
    assert preflight["diff"]["base_ref"] == "main"
    assert preflight["diff"]["source"] == "pr-base"
    assert preflight["paths"]["run_dir"].startswith(".agentpack/reviews/feature-review/")
    assert preflight["paths"]["understanding_output"].startswith(".agentpack/reviews/feature-review/")
    assert preflight["paths"]["findings_output"].startswith(".agentpack/reviews/feature-review/")
    assert preflight["changed_files"] == [
        {
            "path": "src/foo.py",
            "related_tests": ["tests/test_foo.py"],
        }
    ]
    assert preflight["warnings"] == []


def test_review_command_writes_run_scoped_bundle_and_active_aliases(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("agentpack.commands.review_cmd._gh_pr_metadata", lambda _root: None)

    result = CliRunner().invoke(app, ["review", "reviewer is worried about prompt latency"])

    assert result.exit_code == 0, result.output
    preflight_path = repo / ".agentpack" / "review-preflight.json"
    runbook_path = repo / ".agentpack" / "review.prompt.md"
    understanding_prompt_path = repo / ".agentpack" / "review-understanding.prompt.md"
    judge_prompt_path = repo / ".agentpack" / "review-judge.prompt.md"
    assert preflight_path.exists()
    assert runbook_path.exists()
    assert understanding_prompt_path.exists()
    assert judge_prompt_path.exists()

    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    run_dir = repo / preflight["paths"]["run_dir"]
    assert preflight["review_context"] == "reviewer is worried about prompt latency"
    assert preflight["diff"]["range"] == "HEAD~1..HEAD"
    assert preflight["warnings"][0] == "gh PR metadata unavailable; review is using local git context only"
    assert run_dir.exists()
    assert (run_dir / "preflight.json").exists()
    assert (run_dir / "runbook.md").exists()
    assert (run_dir / "understanding.prompt.md").exists()
    assert (run_dir / "judge.prompt.md").exists()
    assert preflight["paths"]["understanding_output"].startswith(".agentpack/reviews/feature-review/")
    assert preflight["paths"]["findings_output"].startswith(".agentpack/reviews/feature-review/")

    runbook = runbook_path.read_text(encoding="utf-8")
    assert "reviewer is worried about prompt latency" in runbook
    assert preflight["review"]["run_id"] in runbook
    assert preflight["paths"]["understanding_output"] in runbook
    assert preflight["paths"]["findings_output"] in runbook
    assert "## Hard Gates" in runbook
    assert "Do not perform the review inline" in runbook
    assert "If you cannot write the Stage 1 output file" in runbook
    assert "Do not start Stage 2 until the Stage 1 output file exists" in runbook
    assert "Do not produce a final review summary unless the Stage 2 output file exists" in runbook

    understanding_prompt = understanding_prompt_path.read_text(encoding="utf-8")
    template = _load_review_template("stage1-understanding.md")
    assert understanding_prompt.startswith(template)
    assert "## AgentPack Run Inputs" in understanding_prompt
    assert "## Execution Gates" in understanding_prompt
    assert "Do not answer inline from this stage prompt." in understanding_prompt
    assert f"Output path: {preflight['paths']['understanding_output']}" in understanding_prompt
    assert understanding_prompt.rstrip().endswith("reviewer is worried about prompt latency")
    assert '"change_units"' in understanding_prompt

    judge_prompt = judge_prompt_path.read_text(encoding="utf-8")
    template = _load_review_template("stage2-judge.md")
    assert judge_prompt.startswith(template)
    assert "## Execution Gates" in judge_prompt
    assert "Do not answer inline from this stage prompt." in judge_prompt
    assert "Do not continue until the declared input TOON exists and has been read from disk." in judge_prompt
    assert f"Input path: {preflight['paths']['understanding_output']}" in judge_prompt
    assert f"Output path: {preflight['paths']['findings_output']}" in judge_prompt
    assert judge_prompt.rstrip().endswith("reviewer is worried about prompt latency")
    assert '"findings"' in judge_prompt


def test_review_command_starts_fresh_and_warns_about_incomplete_previous_run(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("agentpack.commands.review_cmd._gh_pr_metadata", lambda _root: None)
    runner = CliRunner()

    first = runner.invoke(app, ["review", "first pass"])
    assert first.exit_code == 0, first.output
    first_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))
    first_understanding = repo / first_preflight["paths"]["understanding_output"]
    first_understanding.parent.mkdir(parents=True, exist_ok=True)
    first_understanding.write_text("@format toon\n@root review_understanding\nintent:\n  requirement: placeholder\nchange_units[]:\n  []\nopen_questions[]:\n  []\n", encoding="utf-8")

    second = runner.invoke(app, ["review", "second pass"])
    assert second.exit_code == 0, second.output
    second_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))

    assert second_preflight["review"]["run_id"] != first_preflight["review"]["run_id"]
    assert any("incomplete previous review run" in warning for warning in second_preflight["warnings"])
    assert second_preflight["paths"]["run_dir"] != first_preflight["paths"]["run_dir"]


def test_review_command_resume_reuses_existing_run(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("agentpack.commands.review_cmd._gh_pr_metadata", lambda _root: None)
    runner = CliRunner()

    first = runner.invoke(app, ["review", "first pass"])
    assert first.exit_code == 0, first.output
    first_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))
    run_id = first_preflight["review"]["run_id"]

    resumed = runner.invoke(app, ["review", "--resume", run_id, "ignored context"])
    assert resumed.exit_code == 0, resumed.output
    resumed_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))

    assert resumed_preflight["review"]["run_id"] == run_id
    assert resumed_preflight["review"]["mode"] == "resume"
    assert resumed_preflight["review_context"] == "first pass"

def test_review_command_warns_on_invalid_understanding_toon(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("agentpack.commands.review_cmd._gh_pr_metadata", lambda _root: None)
    runner = CliRunner()

    first = runner.invoke(app, ["review", "first pass"])
    assert first.exit_code == 0, first.output
    first_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))
    first_understanding = repo / first_preflight["paths"]["understanding_output"]
    first_understanding.parent.mkdir(parents=True, exist_ok=True)
    first_understanding.write_text("@format toon\nbroken\n", encoding="utf-8")

    second = runner.invoke(app, ["review", "second pass"])
    assert second.exit_code == 0, second.output
    second_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))

    assert any("invalid understanding TOON" in warning for warning in second_preflight["warnings"])

def test_review_command_resume_fails_cleanly_on_invalid_understanding_toon(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("agentpack.commands.review_cmd._gh_pr_metadata", lambda _root: None)
    runner = CliRunner()

    first = runner.invoke(app, ["review", "first pass"])
    assert first.exit_code == 0, first.output
    first_preflight = json.loads((repo / ".agentpack" / "review-preflight.json").read_text(encoding="utf-8"))
    run_id = first_preflight["review"]["run_id"]
    first_understanding = repo / first_preflight["paths"]["understanding_output"]
    first_understanding.parent.mkdir(parents=True, exist_ok=True)
    first_understanding.write_text("@format toon\nbroken\n", encoding="utf-8")

    resumed = runner.invoke(app, ["review", "--resume", run_id])

    assert resumed.exit_code == 1
    assert "Review run artifact invalid" in resumed.output
