from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from agentpack.cli import app
from agentpack.core.models import Receipt
from agentpack.commands.benchmark import (
    BenchmarkCase,
    CaseResult,
    E2ECase,
    _precision_recall,
    _skill_metrics,
    _sample_fixture_cases,
    _load_cases,
    _load_e2e_cases,
    _scaffold_cases,
    _run_case,
    _run_e2e_case,
    _persist_result,
    _load_history_cases,
    _random_baseline,
    _write_results_template,
    _public_benchmark_markdown,
    _write_public_benchmark_table,
    _quality_status,
    _load_public_repo_specs,
    _run_public_repo_suite,
    _public_changed_files,
    _is_test_path,
    _expected_files_touched,
    _unexpected_files_touched,
    _timeout_result,
    _e2e_prompt,
    _ensure_git_commit,
    _e2e_cases_template,
    _estimate_token_cost,
    _process_output_tokens,
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


def test_ensure_git_commit_fetches_missing_shallow_commit(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    cat_file_results = [1, 0]

    def fake_run(command, **kwargs):
        parts = [str(part) for part in command]
        calls.append(parts)
        if parts[:3] == ["git", "cat-file", "-e"]:
            return subprocess.CompletedProcess(parts, cat_file_results.pop(0), "", "")
        return subprocess.CompletedProcess(parts, 0, "", "")

    monkeypatch.setattr("agentpack.commands.benchmark.subprocess.run", fake_run)

    _ensure_git_commit(tmp_path, "abc123")

    assert ["git", "fetch", "--quiet", "--depth", "1", "origin", "abc123"] in calls

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


def test_write_results_template_creates_publishable_markdown(tmp_path: Path) -> None:
    out = _write_results_template(tmp_path, date="2026-05-15")
    content = out.read_text(encoding="utf-8")

    assert out == tmp_path / "benchmarks" / "results" / "2026-05-15.md"
    assert "AgentPack Benchmark Results" in content
    assert "avg recall" in content
    assert "agentpack benchmark --compare --misses" in content


def test_public_benchmark_markdown_renders_table() -> None:
    result = _make_result(
        ["src/auth.py", "tests/test_auth.py"],
        ["src/auth.py"],
        noise_pct=40.0,
        rank_at_k=1,
    )
    result.case.task = "real-api: fix auth token expiry"
    result.case.task_type = "backend-api"

    content = _public_benchmark_markdown([result], suite="real repos", version="0.3.0")

    assert "AgentPack Public Benchmark Table" in content
    assert "real-api" in content
    assert "fix auth token expiry" in content
    assert "avg recall" in content
    assert "| Repo / suite | Task | Type | Mode | Budget | Packed tokens |" in content
    assert "60.0%" in content


def test_write_public_benchmark_table(tmp_path: Path) -> None:
    result = _make_result(["a.py"], ["a.py"], noise_pct=0.0)

    out = _write_public_benchmark_table(tmp_path, [result], suite="real repos", date="2026-05-15")

    assert out == tmp_path / "benchmarks" / "results" / "2026-05-15-public.md"
    assert "real repos" in out.read_text(encoding="utf-8")


def test_benchmark_release_gate_maps_to_public_repo_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "public-repos.toml").write_text("[[repos]]\nname='empty'\nurl='x'\n", encoding="utf-8")
    mocked = _make_result(["a.py"], ["a.py"], noise_pct=0.0)
    mocked.case.task = "repo: fix thing"
    mocked.case.task_type = "python"
    with patch("agentpack.commands.benchmark._load_public_repo_specs", return_value=[SimpleNamespace(name="repo", cases=[object()])]), \
         patch("agentpack.commands.benchmark._run_public_repo_suite", return_value=[mocked]) as run_suite, \
         patch("agentpack.commands.benchmark._write_public_benchmark_table") as write_table:
        result = CliRunner().invoke(app, ["benchmark", "--release-gate", "--no-public-table"])

    assert result.exit_code == 0, result.output
    assert "Release gate" in result.output
    assert run_suite.called
    assert not write_table.called


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
    assert cases[0].task_type == "general"


def test_load_cases_parses_task_type(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text(
        '[[cases]]\ntask = "fix bug"\ntask_type = "backend-api"\nexpected_files = ["a.py"]\n',
        encoding="utf-8",
    )
    cases = _load_cases(f)
    assert cases[0].task_type == "backend-api"


def test_load_cases_parses_workspace(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text(
        '[[cases]]\ntask = "fix bug"\nworkspace = "apps/web"\nexpected_files = ["apps/web/a.ts"]\n',
        encoding="utf-8",
    )
    cases = _load_cases(f)
    assert cases[0].workspace == "apps/web"


def test_load_cases_parses_expected_and_avoid_skills(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text(
        '[[cases]]\n'
        'task = "fix auth bug"\n'
        'expected_skills = ["pytest-debugging", "auth-review"]\n'
        'avoid_skills = ["frontend-review"]\n',
        encoding="utf-8",
    )

    cases = _load_cases(f)

    assert cases[0].expected_skills == ["pytest-debugging", "auth-review"]
    assert cases[0].avoid_skills == ["frontend-review"]


def test_skill_metrics_scores_recall_precision_mrr_and_noise() -> None:
    recall, precision, mrr, noise = _skill_metrics(
        ["pytest-debugging", "frontend-review", "auth-review"],
        expected_skills=["auth-review", "pytest-debugging"],
        avoid_skills=["frontend-review"],
    )

    assert recall == 1.0
    assert precision == pytest.approx(2 / 3)
    assert mrr == 1.0
    assert noise == pytest.approx(1 / 3)


def test_persist_result_records_skill_keyword_quality_metrics(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    result = CaseResult(
        case=BenchmarkCase(
            task="review PR for SQL injection and code quality",
            expected_skills=["code-reviewer"],
            avoid_skills=["generic-writing"],
        ),
        packed_tokens=1000,
        raw_tokens=10000,
        after_ignore_tokens=8000,
        saving_pct=90.0,
        saving_pct_honest=87.5,
        selected_paths=[],
        selected_tokens={},
        changed_covered=0,
        changed_total=0,
        total_s=0.1,
        phase_times={},
        selected_skills=["code-reviewer", "generic-writing"],
        skill_recall_at_3=1.0,
        skill_precision_at_3=0.5,
        skill_mrr=1.0,
        skill_noise_rate=0.5,
        skill_token_cost=245,
    )

    _persist_result(tmp_path, result)

    record = json.loads((tmp_path / ".agentpack" / "benchmark_results.jsonl").read_text(encoding="utf-8"))
    assert record["selected_skills"] == ["code-reviewer", "generic-writing"]
    assert record["skill_recall_at_3"] == 1.0
    assert record["skill_precision_at_3"] == 0.5
    assert record["skill_mrr"] == 1.0
    assert record["skill_noise_rate"] == 0.5
    assert record["skill_token_cost"] == 245


def test_load_cases_defaults_mode(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text('[[cases]]\ntask = "add feature"\n', encoding="utf-8")
    cases = _load_cases(f)
    assert cases[0].mode == "balanced"


def test_load_cases_empty_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "bench.toml"
    f.write_text("", encoding="utf-8")
    assert _load_cases(f) == []


def test_load_public_repo_specs_parses_manifest(tmp_path: Path) -> None:
    f = tmp_path / "public.toml"
    f.write_text(
        '[[repos]]\n'
        'name = "click"\n'
        'url = "https://github.com/pallets/click.git"\n'
        'ref = "main"\n\n'
        '[[repos.cases]]\n'
        'commit = "abc123"\n'
        'task = "fix hidden prompt input"\n'
        'task_type = "python-cli"\n'
        'expected_files = ["src/click/termui.py", "tests/test_termui.py"]\n',
        encoding="utf-8",
    )

    specs = _load_public_repo_specs(f)

    assert len(specs) == 1
    assert specs[0].name == "click"
    assert specs[0].url.endswith("/click.git")
    assert specs[0].cases[0].commit == "abc123"
    assert specs[0].cases[0].expected_files == ["src/click/termui.py", "tests/test_termui.py"]


def test_run_public_repo_suite_uses_parent_checkout(tmp_path: Path) -> None:
    from agentpack.commands import benchmark as benchmark_mod

    spec = benchmark_mod.PublicRepoSpec(
        name="click",
        url="https://example.test/click.git",
        cases=[
            benchmark_mod.PublicRepoCase(
                commit="abc123",
                task="fix prompt",
                expected_files=["src/click/termui.py"],
                task_type="python-cli",
                budget=1200,
            ),
        ],
    )

    with patch("agentpack.commands.benchmark._ensure_public_repo_clone", return_value=tmp_path / "cache"), \
         patch("agentpack.commands.benchmark._ensure_git_commit") as ensure_commit, \
         patch("agentpack.commands.benchmark._git_stdout", return_value="parent123") as git_stdout, \
         patch("agentpack.commands.benchmark._run_git") as run_git, \
         patch("agentpack.commands.benchmark.shutil.copytree") as copytree, \
         patch("agentpack.commands.benchmark._run_case") as run_case:
        run_case.side_effect = lambda _root, case: _make_result(["src/click/termui.py"], case.expected_files)
        results = _run_public_repo_suite(tmp_path, [spec], cache_dir=tmp_path / "cache")

    assert len(results) == 1
    case_arg = run_case.call_args.args[1]
    assert case_arg.task == "click: fix prompt"
    assert case_arg.task_type == "python-cli"
    assert case_arg.budget == 1200
    assert [call.args for call in ensure_commit.call_args_list] == [
        (tmp_path / "cache", "abc123"),
        (tmp_path / "cache", "parent123"),
    ]
    git_stdout.assert_called_once_with(tmp_path / "cache", ["rev-parse", "abc123^"])
    copytree.assert_called_once()
    assert any(call.args[1] == ["checkout", "--quiet", "parent123"] for call in run_git.call_args_list)


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
    assert record["task_type"] == "general"
    assert record["after_ignore_tokens"] == 8000
    assert "saving_pct_honest" in record
    assert record["rank_at_k"] == 3
    assert record["noise_pct"] == pytest.approx(30.0)
    assert record["token_precision"] == pytest.approx(0.7)
    assert record["random_f1"] == pytest.approx(0.2)


def test_quality_status_passes_on_recall_and_token_precision() -> None:
    result = _make_result(
        ["a.py", "b.py"],
        ["a.py"],
        noise_pct=40.0,
    )
    passed, metrics = _quality_status([result])

    assert passed is True
    assert metrics["avg_recall"] == 1.0
    assert metrics["avg_token_precision"] == pytest.approx(0.6)


def test_quality_status_fails_without_expected_files() -> None:
    passed, metrics = _quality_status([_make_result(["a.py"], [])])

    assert passed is False
    assert metrics["cases"] == 0


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
    plan.changed_files_source = "git working tree"
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
        "basis": mock_plan.changed_files_source,
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
    assert {
        "py_fastapi_app",
        "nextjs_app",
        "mixed_repo",
        "django_rest_app",
        "go_service",
        "rails_app",
    } <= fixture_names
    assert all(c.root.exists() for c in fixture_cases)
    assert all(c.case.expected_files for c in fixture_cases)
    assert {c.case.task_type for c in fixture_cases} >= {"backend-api", "frontend-web", "infrastructure"}


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


def test_load_e2e_cases_reads_guard_and_expected_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cases = tmp_path / "cases.toml"
    cases.write_text(
        f"""
[[cases]]
name = "guarded"
repo = "{repo}"
task = "fix guarded case"
test_command = "pytest"
protected_paths = ["tests/test_guard.py"]
expected_edit_paths = ["src/guard.py"]
""",
        encoding="utf-8",
    )

    loaded = _load_e2e_cases(tmp_path, cases)

    assert loaded[0].protected_paths == ["tests/test_guard.py"]
    assert loaded[0].expected_edit_paths == ["src/guard.py"]


def test_e2e_changed_file_classification_helpers() -> None:
    changed = _public_changed_files([
        ".agentpack_e2e_prompt.txt",
        ".agentpack/",
        "src/__pycache__/",
        "src/app.py",
        "tests/test_app.py",
        "frontend/button.test.tsx",
    ])

    assert changed == ["frontend/button.test.tsx", "src/app.py", "tests/test_app.py"]
    assert _is_test_path("tests/test_app.py")
    assert _is_test_path("frontend/button.test.tsx")
    assert not _is_test_path("src/app.py")
    assert _expected_files_touched(changed, ["src/app.py"]) == ["src/app.py"]
    assert _unexpected_files_touched(changed, ["src/app.py"]) == ["frontend/button.test.tsx", "tests/test_app.py"]
    assert _unexpected_files_touched(changed, []) == []


def test_timeout_result_records_failed_process() -> None:
    exc = subprocess.TimeoutExpired(["agent"], timeout=7, output=b"partial", stderr=b"slow")

    result = _timeout_result(["agent"], exc)

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert "Timed out after 7 seconds" in result.stderr


def test_e2e_cost_helpers_estimate_prompt_and_output_cost() -> None:
    result = subprocess.CompletedProcess(args=["agent"], returncode=0, stdout="hello world", stderr="done")

    assert _process_output_tokens(result) >= 1
    assert _estimate_token_cost(1_000_000, 2.5) == 2.5
    assert _estimate_token_cost(1000, 0.0) == 0.0


def test_run_e2e_case_fails_when_protected_file_changes(tmp_path: Path) -> None:
    repo = tmp_path / "source"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_guard.py").write_text("def test_guard():\n    assert True\n", encoding="utf-8")
    agent = tmp_path / "agent.py"
    agent.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1], 'tests/test_guard.py').write_text('def test_guard():\\n    assert True\\n# edited\\n')\n",
        encoding="utf-8",
    )
    case = E2ECase(
        name="protected",
        repo=repo,
        task="do not edit tests",
        test_command="python -c 'pass'",
        protected_paths=["tests/test_guard.py"],
        expected_edit_paths=["src/app.py"],
    )

    result = _run_e2e_case(
        case,
        strategy="no-context",
        trial=1,
        agent_command=f"python {agent} {{repo}} {{prompt}}",
        timeout=10,
        input_cost_per_mtok=1.0,
        output_cost_per_mtok=2.0,
        keep_workdir=True,
    )

    assert not result.passed
    assert result.protected_files_changed == ["tests/test_guard.py"]
    assert result.test_files_changed == ["tests/test_guard.py"]
    assert result.missing_expected_edits == ["src/app.py"]
    assert result.agent_output_tokens >= 1
    assert result.estimated_total_cost_usd > 0


def test_e2e_hybrid_prompt_combines_grep_and_lite(tmp_path: Path) -> None:
    case = E2ECase(name="hybrid", repo=tmp_path, task="fix auth", test_command="pytest")

    with patch("agentpack.commands.benchmark._grep_context", return_value="grep-hit"), \
         patch("agentpack.commands.benchmark._agentpack_lite_context", return_value="lite-map"):
        prompt = _e2e_prompt(case, "hybrid", tmp_path)

    assert "grep-hit" in prompt
    assert "lite-map" in prompt


def test_e2e_agentpack_lite_prompt_uses_compact_map(tmp_path: Path) -> None:
    case = E2ECase(name="lite", repo=tmp_path, task="fix refund", test_command="pytest")
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text(
        "[context_lite]\nbudget = 1234\nmax_selected_files = 1\nmax_omitted_files = 1\nmax_stubs = 1\nsummary_chars = 50\n",
        encoding="utf-8",
    )
    selected = SimpleNamespace(
        path="src/refund.py",
        include_mode="summary",
        score=123.0,
        reasons=["keyword match"],
        summary="Refund service summary",
        symbols=[SimpleNamespace(signature="def refund_order(order_id):")],
    )
    omitted = SimpleNamespace(
        path="api/refund_route.py",
        risk="high",
        score=95.0,
        reasons=["caller of refund_order"],
        omission_reason="budget exhausted",
    )
    fake_result = SimpleNamespace(
        pack=SimpleNamespace(
            selected_files=[selected],
            omitted_relevant_files=[omitted],
            changed_files=["src/refund.py"],
        )
    )

    with patch("agentpack.commands.benchmark.PackService") as service:
        service.return_value.run.return_value = fake_result
        prompt = _e2e_prompt(case, "agentpack-lite", tmp_path)

    request = service.return_value.run.call_args.args[0]
    assert request.budget == 1234
    assert request.mode == "lite"
    assert "Selected File Map" in prompt
    assert "`src/refund.py`" in prompt
    assert "High-Risk Omitted Files" in prompt
    assert "`api/refund_route.py`" in prompt
    assert "def refund_order(order_id):" in prompt


def test_e2e_cases_template_scaffolds_guarded_hard_categories(tmp_path: Path) -> None:
    content = _e2e_cases_template(tmp_path)

    assert "caller_signature_change" in content
    assert "api_service_model_contract" in content
    assert "protected_paths" in content
    assert "expected_edit_paths" in content
    assert "agentpack-lite,hybrid,agentpack" in content


def test_benchmark_e2e_init_writes_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["benchmark", "e2e-init"])

    assert result.exit_code == 0, result.output
    out = tmp_path / ".agentpack" / "e2e_cases.toml"
    assert out.exists()
    assert "guarded E2E benchmark cases" in out.read_text(encoding="utf-8")
