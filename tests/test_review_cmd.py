from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.commands.review_cmd import _build_review_preflight, _review_output_paths


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
    assert preflight["diff"]["base_ref"] == "main"
    assert preflight["diff"]["source"] == "pr-base"
    assert preflight["paths"]["understanding_output"] == "feature-review_understanding.json"
    assert preflight["paths"]["findings_output"] == "feature-review_findings.json"
    assert preflight["changed_files"] == [
        {
            "path": "src/foo.py",
            "related_tests": ["tests/test_foo.py"],
        }
    ]
    assert preflight["warnings"] == []


def test_review_command_writes_staged_bundle(tmp_path, monkeypatch) -> None:
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
    assert preflight["review_context"] == "reviewer is worried about prompt latency"
    assert preflight["diff"]["range"] == "HEAD~1..HEAD"
    assert preflight["warnings"][0] == "gh PR metadata unavailable; review is using local git context only"
    assert preflight["paths"]["understanding_output"] == "feature-review_understanding.json"
    assert preflight["paths"]["findings_output"] == "feature-review_findings.json"

    runbook = runbook_path.read_text(encoding="utf-8")
    assert "reviewer is worried about prompt latency" in runbook
    assert "feature-review_understanding.json" in runbook
    assert "feature-review_findings.json" in runbook

    understanding_prompt = understanding_prompt_path.read_text(encoding="utf-8")
    assert "Output path: feature-review_understanding.json" in understanding_prompt
    assert "Stage 1 — Understanding" in understanding_prompt
    assert '"change_units"' in understanding_prompt

    judge_prompt = judge_prompt_path.read_text(encoding="utf-8")
    assert "Input path: feature-review_understanding.json" in judge_prompt
    assert "Output path: feature-review_findings.json" in judge_prompt
    assert "Stage 2 — Judge" in judge_prompt
    assert '"findings"' in judge_prompt
