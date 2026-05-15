from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.commands.tune import _build_tuning_suggestions, _write_tuning_report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_tuning_suggestions_from_noisy_metrics(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / ".agentpack" / "metrics.jsonl",
        [
            {
                "selection_recall": 0.5,
                "selection_token_precision": 0.05,
                "selection_token_context_precision": 0.4,
                "selection_token_precision_summary": 0.0,
                "selection_noise_paths": ["src/noise.py", "src/noise.py", "docs/blob.md"],
            }
        ],
    )

    suggestions = _build_tuning_suggestions(tmp_path)
    areas = {item.area for item in suggestions}

    assert {"mode", "metrics", "summaries", "noise", "benchmark"}.issubset(areas)


def test_build_tuning_suggestions_from_benchmark_misses(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / ".agentpack" / "benchmark_results.jsonl",
        [
            {
                "task": "fix auth",
                "misses": [
                    {"path": "src/auth.py", "status": "budget cut"},
                    {"path": "tests/test_auth.py", "status": "ignored by .agentignore"},
                ],
            }
        ],
    )

    suggestions = _build_tuning_suggestions(tmp_path)

    assert any(item.area == "benchmark misses" and "budget" in item.finding for item in suggestions)
    assert any(item.area == "benchmark misses" and "ignored" in item.finding for item in suggestions)


def test_write_tuning_report(tmp_path: Path) -> None:
    suggestions = _build_tuning_suggestions(tmp_path)
    out = _write_tuning_report(tmp_path, suggestions)

    assert out == tmp_path / ".agentpack" / "tuning.md"
    assert "AgentPack Tuning Suggestions" in out.read_text(encoding="utf-8")


def test_tune_cli_writes_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_jsonl(
        tmp_path / ".agentpack" / "metrics.jsonl",
        [{"selection_recall": 0.1, "selection_token_precision": 0.01}],
    )

    result = CliRunner().invoke(app, ["tune", "--write"])

    assert result.exit_code == 0
    assert "AgentPack Tuning Suggestions" in result.output
    assert (tmp_path / ".agentpack" / "tuning.md").exists()
