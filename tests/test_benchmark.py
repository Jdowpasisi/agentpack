from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agentpack.commands.benchmark import (
    BenchmarkCase,
    CaseResult,
    _precision_recall,
    _load_cases,
    _scaffold_cases,
    _run_case,
)


# ---------------------------------------------------------------------------
# _precision_recall
# ---------------------------------------------------------------------------

def _make_result(selected: list[str], expected: list[str]) -> CaseResult:
    return CaseResult(
        case=BenchmarkCase(task="t", expected_files=expected),
        packed_tokens=1000,
        raw_tokens=10000,
        saving_pct=90.0,
        selected_paths=selected,
        changed_covered=0,
        changed_total=0,
        total_s=0.1,
        phase_times={},
    )


def test_precision_recall_perfect() -> None:
    r = _make_result(["a.py", "b.py"], ["a.py", "b.py"])
    p, rec, f1 = _precision_recall(r)
    assert p == 1.0
    assert rec == 1.0
    assert f1 == 1.0


def test_precision_recall_zero_recall() -> None:
    r = _make_result(["c.py", "d.py"], ["a.py", "b.py"])
    p, rec, f1 = _precision_recall(r)
    assert p == 0.0
    assert rec == 0.0
    assert f1 == 0.0


def test_precision_recall_partial() -> None:
    r = _make_result(["a.py", "c.py"], ["a.py", "b.py"])
    p, rec, f1 = _precision_recall(r)
    assert p == pytest.approx(0.5)
    assert rec == pytest.approx(0.5)
    assert f1 == pytest.approx(0.5)


def test_precision_recall_no_expected_returns_zeros() -> None:
    r = _make_result(["a.py"], [])
    p, rec, f1 = _precision_recall(r)
    assert p == 0.0 and rec == 0.0 and f1 == 0.0


def test_precision_recall_empty_selected() -> None:
    r = _make_result([], ["a.py"])
    p, rec, f1 = _precision_recall(r)
    assert f1 == 0.0


# ---------------------------------------------------------------------------
# _scaffold_cases
# ---------------------------------------------------------------------------

def test_scaffold_cases_creates_file(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    out = _scaffold_cases(tmp_path)
    assert out.exists()
    assert "[[cases]]" in out.read_text()


def test_scaffold_cases_idempotent(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    out1 = _scaffold_cases(tmp_path)
    out1.write_text("existing content", encoding="utf-8")
    out2 = _scaffold_cases(tmp_path)
    assert out2.read_text() == "existing content"


# ---------------------------------------------------------------------------
# _load_cases
# ---------------------------------------------------------------------------

def test_load_cases_parses_toml(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text(
        '[[cases]]\ntask = "fix bug"\nmode = "minimal"\nexpected_files = ["a.py"]\n',
        encoding="utf-8",
    )
    cases = _load_cases(f)
    assert len(cases) == 1
    assert cases[0].task == "fix bug"
    assert cases[0].mode == "minimal"
    assert cases[0].expected_files == ["a.py"]


def test_load_cases_defaults_mode(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text('[[cases]]\ntask = "add feature"\n', encoding="utf-8")
    cases = _load_cases(f)
    assert cases[0].mode == "balanced"


def test_load_cases_empty_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text("", encoding="utf-8")
    assert _load_cases(f) == []


# ---------------------------------------------------------------------------
# _run_case via CLI invocation
# ---------------------------------------------------------------------------

def _make_mock_plan(files: int = 10, tokens: int = 5000):
    fi = MagicMock()
    fi.estimated_tokens = 100
    fi.path = "src/foo.py"

    scan_result = MagicMock()
    scan_result.packable = [fi]
    scan_result.all_files = [fi] * files

    sf = MagicMock()
    sf.path = "src/foo.py"
    sf.content = "x" * 100
    sf.summary = ""
    sf.symbols = []

    plan = MagicMock()
    plan.selected = [sf]
    plan.scan_result = scan_result
    plan.all_changed = {"src/foo.py"}
    plan.phase_times = {"scan": 0.1, "rank": 0.05}
    return plan


def test_run_case_returns_result(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix bug", mode="balanced")
    mock_plan = _make_mock_plan()

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=500):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _run_case(tmp_path, case)

    assert result.packed_tokens > 0
    assert result.saving_pct >= 0
    assert result.total_s >= 0
    assert result.changed_covered == 1
    assert result.changed_total == 1


def test_benchmark_cli_single_task(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from agentpack.cli import app
    import os
    os.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    mock_plan = _make_mock_plan()
    runner = CliRunner()

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=500):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = runner.invoke(app, ["benchmark", "--task", "fix auth bug"])

    assert result.exit_code == 0
    assert "fix auth bug" in result.output


def test_benchmark_cli_init(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from agentpack.cli import app
    import os
    os.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["benchmark", "--init"])
    assert result.exit_code == 0
    assert (tmp_path / ".agentpack" / "benchmark.toml").exists()
