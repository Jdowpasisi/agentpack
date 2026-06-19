from __future__ import annotations

import json

from agentpack.core.e2e_benchmark import E2ERunMetrics, append_e2e_result, e2e_scaffold_markdown


def test_e2e_metrics_record_expected_fields(tmp_path) -> None:
    path = tmp_path / ".agentpack" / "e2e_results.jsonl"
    metrics = E2ERunMetrics(
        case_id="auth-pr-review",
        variant="agentpack",
        task_success=True,
        validation_passed=True,
        token_usage=12000,
        estimated_cost_usd=0.42,
        turns=3,
        tool_calls=12,
        time_to_first_correct_file_seconds=8.5,
        wall_time_seconds=90.0,
        final_edited_files=["src/auth.py", "README.md"],
        expected_files=["src/auth.py"],
        agentpack_noise=["surfaced README for code-only task"],
    )

    append_e2e_result(path, metrics)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["variant"] == "agentpack"
    assert record["task_success"] is True
    assert record["validation_passed"] is True
    assert record["time_to_first_correct_file_seconds"] == 8.5
    assert record["unexpected_edited_files"] == ["README.md"]
    assert record["agentpack_noise"] == ["surfaced README for code-only task"]


def test_e2e_scaffold_does_not_overclaim_cost_savings() -> None:
    text = e2e_scaffold_markdown()

    assert "baseline" in text
    assert "agentpack" in text
    assert "token usage and estimated cost" in text
    assert "Do not claim cost" in text
