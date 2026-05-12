from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agentpack.core.models import Receipt
from agentpack.commands.benchmark import (
    BenchmarkCase,
    CaseResult,
    _precision_recall,
    _sample_fixture_cases,
    _load_cases,
    _scaffold_cases,
    _run_case,
    _persist_result,
    _load_history_cases,
    _random_baseline,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_result(
    selected: list[str],
    expected: list[str],
    *,
    packed_tokens: int = 1000,
    raw_tokens: int = 10000,
    after_ignore_tokens: int = 8000,
    rank_at_k: int | None = None,
    noise_pct: float | None = None,
    random_f1: float | None = None,
    missed_expected: list[dict] | None = None,
) -> CaseResult:
    return CaseResult(
        case=BenchmarkCase(task="t", expected_files=expected),
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        after_ignore_tokens=after_ignore_tokens,
        saving_pct=(1 - packed_tokens / raw_tokens) * 100,
        saving_pct_honest=(1 - packed_tokens / after_ignore_tokens) * 100,
        selected_paths=selected,
        selected_tokens={p: 100 for p in selected},
        changed_covered=0,
        changed_total=0,
        total_s=0.1,
        phase_times={},
        rank_at_k=rank_at_k,
        noise_pct=noise_pct,
        random_precision=None,
        random_recall=None,
        random_f1=random_f1,
        missed_expected=missed_expected or [],
    )


# ---------------------------------------------------------------------------
# _precision_recall
# ---------------------------------------------------------------------------

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
# saving_pct fields
# ---------------------------------------------------------------------------

def test_saving_pct_honest_lower_than_vs_raw() -> None:
    r = _make_result(["a.py"], [], packed_tokens=500, raw_tokens=10000, after_ignore_tokens=2000)
    assert r.saving_pct == pytest.approx(95.0)
    assert r.saving_pct_honest == pytest.approx(75.0)
    assert r.saving_pct_honest < r.saving_pct


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
# _persist_result
# ---------------------------------------------------------------------------

def test_persist_result_writes_jsonl(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    r = _make_result(["a.py", "b.py"], ["a.py"], rank_at_k=3, noise_pct=30.0, random_f1=0.2)
    _persist_result(tmp_path, r)

    out = tmp_path / ".agentpack" / "benchmark_results.jsonl"
    assert out.exists()
    record = json.loads(out.read_text().strip())
    assert record["task"] == "t"
    assert record["after_ignore_tokens"] == 8000
    assert "saving_pct_honest" in record
    assert record["rank_at_k"] == 3
    assert record["noise_pct"] == pytest.approx(30.0)
    assert record["random_f1"] == pytest.approx(0.2)


def test_persist_result_appends(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    r = _make_result(["a.py"], [])
    _persist_result(tmp_path, r)
    _persist_result(tmp_path, r)
    lines = (tmp_path / ".agentpack" / "benchmark_results.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_persist_result_no_gt_fields_are_none(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    r = _make_result(["a.py"], [])
    _persist_result(tmp_path, r)
    record = json.loads((tmp_path / ".agentpack" / "benchmark_results.jsonl").read_text().strip())
    assert record["precision"] is None
    assert record["rank_at_k"] is None
    assert record["noise_pct"] is None


# ---------------------------------------------------------------------------
# _load_history_cases
# ---------------------------------------------------------------------------

def test_load_history_cases_returns_unique_tasks(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    metrics = tmp_path / ".agentpack" / "metrics.jsonl"
    records = [
        {"task": "fix auth", "mode": "balanced"},
        {"task": "fix auth", "mode": "balanced"},  # duplicate
        {"task": "add rate limit", "mode": "deep"},
        {"task": "refactor db", "mode": "minimal"},
    ]
    metrics.write_text("\n".join(json.dumps(r) for r in records))
    cases = _load_history_cases(tmp_path, 10)
    tasks = [c.task for c in cases]
    assert len(tasks) == len(set(tasks))
    assert set(tasks) == {"fix auth", "add rate limit", "refactor db"}


def test_load_history_cases_respects_n(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    metrics = tmp_path / ".agentpack" / "metrics.jsonl"
    records = [{"task": f"task {i}", "mode": "balanced"} for i in range(10)]
    metrics.write_text("\n".join(json.dumps(r) for r in records))
    cases = _load_history_cases(tmp_path, 3)
    assert len(cases) == 3


def test_load_history_cases_missing_file(tmp_path: Path) -> None:
    cases = _load_history_cases(tmp_path, 5)
    assert cases == []


# ---------------------------------------------------------------------------
# _random_baseline
# ---------------------------------------------------------------------------

def test_random_baseline_respects_budget() -> None:
    paths = [f"f{i}.py" for i in range(20)]
    token_map = {p: 100 for p in paths}
    selected, p, r, f1 = _random_baseline(paths, token_map, ["f0.py", "f1.py"], budget=500)
    total = sum(token_map.get(p, 0) for p in selected)
    assert total <= 500


def test_random_baseline_no_expected_returns_zeros() -> None:
    _, p, r, f1 = _random_baseline(["a.py"], {"a.py": 100}, [], budget=1000)
    assert p == 0.0 and r == 0.0 and f1 == 0.0


def test_random_baseline_perfect_hit() -> None:
    paths = ["a.py"]
    _, p, r, f1 = _random_baseline(paths, {"a.py": 100}, ["a.py"], budget=1000)
    assert f1 == 1.0


# ---------------------------------------------------------------------------
# _run_case (mocked plan)
# ---------------------------------------------------------------------------

def _make_mock_plan(files: int = 10, tokens: int = 5000):
    fi = MagicMock()
    fi.estimated_tokens = 100
    fi.path = "src/foo.py"
    fi.ignored = False
    fi.binary = False

    scan_result = MagicMock()
    scan_result.packable = [fi]
    scan_result.all_files = [fi] * files

    sf = MagicMock()
    sf.path = "src/foo.py"
    sf.content = "x" * 100
    sf.summary = ""
    sf.symbols = []

    scored_fi = MagicMock()
    scored_fi.path = "src/foo.py"

    plan = MagicMock()
    plan.selected = [sf]
    plan.scan_result = scan_result
    plan.all_changed = {"src/foo.py"}
    plan.phase_times = {"scan": 0.1, "rank": 0.05}
    plan.scored = [(scored_fi, 1.0, ["keyword_match"])]
    plan.receipts = []
    return plan


def test_run_case_returns_result(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix bug", mode="balanced")
    mock_plan = _make_mock_plan()

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=50):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _run_case(tmp_path, case)

    assert result.packed_tokens > 0
    assert result.saving_pct >= 0
    assert result.saving_pct_honest >= 0
    assert result.after_ignore_tokens > 0
    assert result.total_s >= 0
    assert result.changed_covered == 1
    assert result.changed_total == 1
    assert result.selected_tokens is not None


def test_run_case_with_expected_files_sets_quality_fields(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix bug", mode="balanced", expected_files=["src/foo.py"])
    mock_plan = _make_mock_plan()

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=50):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _run_case(tmp_path, case)

    assert result.rank_at_k == 1
    assert result.noise_pct is not None
    assert result.random_f1 is not None


def test_run_case_records_miss_diagnostics(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix bug", mode="balanced", expected_files=["src/foo.py", "src/missing.py"])
    mock_plan = _make_mock_plan()
    mock_plan.receipts = [Receipt(path="src/missing.py", action="excluded", reason="budget exhausted")]

    missing_fi = MagicMock()
    missing_fi.path = "src/missing.py"
    missing_fi.estimated_tokens = 200
    missing_fi.ignored = False
    missing_fi.binary = False
    mock_plan.scan_result.packable = mock_plan.scan_result.packable + [missing_fi]
    mock_plan.scan_result.all_files = mock_plan.scan_result.all_files + [missing_fi]
    mock_plan.scored = mock_plan.scored + [(missing_fi, 42.0, ["filename keyword match"])]

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=50):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _run_case(tmp_path, case)

    assert result.missed_expected == [{
        "path": "src/missing.py",
        "status": "budget exhausted",
        "rank": 2,
        "score": 42.0,
        "reasons": ["filename keyword match"],
    }]


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


def test_benchmark_cli_from_history(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from agentpack.cli import app
    import os
    os.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()

    metrics = tmp_path / ".agentpack" / "metrics.jsonl"
    metrics.write_text(json.dumps({"task": "fix auth", "mode": "balanced"}) + "\n")

    mock_plan = _make_mock_plan()
    runner = CliRunner()

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=500):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = runner.invoke(app, ["benchmark", "--from-history", "5"])

    assert result.exit_code == 0
    assert "fix auth" in result.output


def test_sample_fixture_cases_include_framework_repos() -> None:
    fixtures_root = Path(__file__).parent / "fixtures"
    fixture_cases = _sample_fixture_cases(fixtures_root)

    fixture_names = {c.fixture for c in fixture_cases}
    assert {"py_fastapi_app", "nextjs_app", "mixed_repo"} <= fixture_names
    assert all(c.root.exists() for c in fixture_cases)
    assert all(c.case.expected_files for c in fixture_cases)


def test_benchmark_cli_sample_fixtures_uses_temp_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner
    from agentpack.cli import app

    source_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(source_root)

    runner = CliRunner()
    fixture_agentpack = source_root / "tests" / "fixtures" / "py_fastapi_app" / ".agentpack"

    with patch("agentpack.commands.benchmark._run_case") as run_case:
        run_case.side_effect = lambda _root, _case: _make_result(["src/app/auth.py"], ["src/app/auth.py"])
        result = runner.invoke(app, ["benchmark", "--sample-fixtures"])

    assert result.exit_code == 0
    assert "sample fixture benchmark" in result.output
    assert "py_fastapi_app" in result.output
    assert not fixture_agentpack.exists()


def test_benchmark_result_persisted_after_run(tmp_path: Path) -> None:
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
        runner.invoke(app, ["benchmark", "--task", "fix auth bug"])

    out = tmp_path / ".agentpack" / "benchmark_results.jsonl"
    assert out.exists()
    record = json.loads(out.read_text().strip())
    assert record["task"] == "fix auth bug"
    assert "saving_pct_honest" in record
    assert "after_ignore_tokens" in record
    assert "misses" in record


def test_benchmark_cli_misses_prints_diagnostics(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from agentpack.cli import app
    import os
    os.chdir(tmp_path)
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "benchmark.toml").write_text(
        '[[cases]]\n'
        'task = "fix kundali"\n'
        'expected_files = ["backend/src/services/astrology.service.ts"]\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    mocked = _make_result(
        selected=["frontend/app/charts/page.tsx"],
        expected=["backend/src/services/astrology.service.ts"],
        missed_expected=[{
            "path": "backend/src/services/astrology.service.ts",
            "status": "summary score below floor",
            "rank": 18,
            "score": 54.0,
            "reasons": ["filename keyword match"],
        }],
    )

    with patch("agentpack.commands.benchmark._run_case", return_value=mocked):
        result = runner.invoke(app, ["benchmark", "--misses"])

    assert result.exit_code == 0
    assert "miss details" in result.output
    assert "astrology.service.ts" in result.output
