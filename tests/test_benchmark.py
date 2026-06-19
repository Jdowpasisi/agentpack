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
    PublicRepoCase,
    PublicRepoSpec,
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
    _filter_public_repo_specs,
    _ensure_public_repo_clone,
    _run_public_repo_suite,
    _public_changed_files,
    _public_commit_changed_files,
    _sample_public_history_cases,
    _write_anonymous_benchmark_report,
    _is_test_path,
    _expected_files_touched,
    _unexpected_files_touched,
    _timeout_result,
    _e2e_prompt,
    _e2e_ab_metrics,
    _e2e_ab_markdown,
    _ensure_git_commit,
    _e2e_cases_template,
    _estimate_token_cost,
    _process_output_tokens,
    _estimate_agent_tool_calls,
    _time_to_first_expected_file,
    _candidate_recall_at,
    _candidate_precision_at,
    _miss_failure_type,
    _path_family,
    _reason_family_precision,
    _selected_family_tokens,
    _low_budget_extra_file_waste,
    _low_budget_waste_summary,
    _write_results_jsonl,
    _replacement_pair_diagnostics,
    _same_scope_replacement_opportunities,
    _plausibly_useful_selected_noise,
    _label_audit_summary,
    _benchmark_intent_profile,
    _owner_file_recall,
    _expected_family_recall,
    _expected_include_mode_diagnostics,
    _expected_rank_distribution,
    _package_boundary_diagnostics,
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
    candidate_recall_at_20: float | None = None,
    candidate_recall_at_50: float | None = None,
    candidate_recall_at_100: float | None = None,
    candidate_precision_at_3: float | None = None,
    candidate_precision_at_5: float | None = None,
    low_budget_extra_file_waste: int | None = None,
    precision_delta_if_drop_last_summary: float | None = None,
    expected_token_coverage: float | None = None,
    selected_family_tokens: dict[str, int] | None = None,
    selected_family_waste_tokens: dict[str, int] | None = None,
    reason_family_precision: dict[str, dict[str, float]] | None = None,
    failure_type_counts: dict[str, int] | None = None,
    noise_pct: float | None = None,
    random_f1: float | None = None,
    missed_expected: list[dict] | None = None,
    top_candidates: list[dict] | None = None,
    selection_diagnostics: dict | None = None,
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
        candidate_recall_at_20=candidate_recall_at_20,
        candidate_recall_at_50=candidate_recall_at_50,
        candidate_recall_at_100=candidate_recall_at_100,
        candidate_precision_at_3=candidate_precision_at_3,
        candidate_precision_at_5=candidate_precision_at_5,
        low_budget_extra_file_waste=low_budget_extra_file_waste,
        precision_delta_if_drop_last_summary=precision_delta_if_drop_last_summary,
        expected_token_coverage=expected_token_coverage,
        selected_family_tokens=selected_family_tokens or {},
        selected_family_waste_tokens=selected_family_waste_tokens or {},
        reason_family_precision=reason_family_precision or {},
        failure_type_counts=failure_type_counts or {},
        noise_pct=noise_pct,
        random_precision=None,
        random_recall=None,
        random_f1=random_f1,
        missed_expected=missed_expected or [],
        top_candidates=top_candidates or [],
        selection_diagnostics=selection_diagnostics or {},
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


def test_candidate_recall_at_k_counts_expected_files_in_ranked_candidates() -> None:
    scored_paths = ["noise.py", "a.py", "more_noise.py", "b.py"]

    assert _candidate_recall_at(scored_paths, {"a.py", "b.py", "c.py"}, 2) == pytest.approx(1 / 3)
    assert _candidate_recall_at(scored_paths, {"a.py", "b.py", "c.py"}, 4) == pytest.approx(2 / 3)
    assert _candidate_recall_at(scored_paths, set(), 4) == 0.0


def test_candidate_precision_at_k_counts_noise_in_ranked_candidates() -> None:
    scored_paths = ["noise.py", "a.py", "more_noise.py", "b.py"]

    assert _candidate_precision_at(scored_paths, {"a.py", "b.py"}, 3) == pytest.approx(1 / 3)
    assert _candidate_precision_at(scored_paths, {"a.py", "b.py"}, 4) == pytest.approx(0.5)
    assert _candidate_precision_at([], {"a.py"}, 4) == 0.0


def test_path_family_and_selected_family_tokens_group_noise_sources() -> None:
    tokens = {
        "src/parser.ts": 100,
        "playground/css/index.ts": 200,
        "docs/parser.md": 300,
        "tests/parser.spec.ts": 400,
        "package.json": 50,
    }

    assert _path_family("src/parser.ts") == "source"
    assert _path_family("playground/css/index.ts") == "examples"
    assert _path_family("docs/parser.md") == "docs"
    assert _selected_family_tokens(list(tokens), tokens) == {
        "config": 50,
        "docs": 300,
        "examples": 200,
        "source": 100,
        "test": 400,
    }


def test_reason_family_precision_counts_expected_signal_quality() -> None:
    selected = [
        SimpleNamespace(path="src/expected.py", reasons=["filename keyword match", "content keyword match (2)"]),
        SimpleNamespace(path="docs/noise.md", reasons=["filename keyword match", "matched role keyword: docs"]),
    ]

    stats = _reason_family_precision(selected, {"src/expected.py"})

    assert stats["filename"]["selected"] == 2
    assert stats["filename"]["expected"] == 1
    assert stats["filename"]["precision"] == pytest.approx(0.5)
    assert stats["content"]["precision"] == pytest.approx(1.0)
    assert stats["summary"]["precision"] == pytest.approx(0.0)


def test_miss_failure_type_classifies_benchmark_funnel_stage() -> None:
    fi = SimpleNamespace()

    assert _miss_failure_type(fi=None, scored_info=None, status="", selected_count=3) == "EXPECTED_NOT_FOUND"
    assert _miss_failure_type(fi=fi, scored_info=None, status="", selected_count=3) == "EXPECTED_NOT_SCORED"
    assert _miss_failure_type(
        fi=fi,
        scored_info={"rank": 120, "score": 10},
        status="ranked but not selected",
        selected_count=3,
    ) == "EXPECTED_RANKED_LOW"
    assert _miss_failure_type(
        fi=fi,
        scored_info={"rank": 5, "score": 100},
        status="compressed context cap reached",
        selected_count=3,
    ) == "EXPECTED_SKIPPED"
    assert _miss_failure_type(
        fi=fi,
        scored_info={"rank": 4, "score": 100},
        status="ranked but not selected",
        selected_count=3,
    ) == "NOISE_SELECTED_ABOVE_EXPECTED"


def test_low_budget_extra_file_waste_reports_drop_last_summary_delta() -> None:
    selected = [
        SimpleNamespace(path="expected.py", include_mode="summary"),
        SimpleNamespace(path="noise.py", include_mode="summary"),
    ]

    waste, delta = _low_budget_extra_file_waste(
        selected=selected,
        selected_tokens={"expected.py": 100, "noise.py": 100},
        expected_files={"expected.py"},
        packed_tokens=200,
        expected_tokens=100,
        budget=2000,
        changed_files_source="no live changes detected",
    )

    assert waste == 100
    assert delta == pytest.approx(0.5)


def test_low_budget_extra_file_waste_ignores_expected_last_summary() -> None:
    selected = [
        SimpleNamespace(path="noise.py", include_mode="summary"),
        SimpleNamespace(path="expected.py", include_mode="summary"),
    ]

    waste, delta = _low_budget_extra_file_waste(
        selected=selected,
        selected_tokens={"expected.py": 100, "noise.py": 100},
        expected_files={"expected.py"},
        packed_tokens=200,
        expected_tokens=100,
        budget=2000,
        changed_files_source="no live changes detected",
    )

    assert waste == 0
    assert delta == pytest.approx(-0.5)


def test_low_budget_waste_summary_averages_observed_cases() -> None:
    rows = [
        _make_result(
            ["expected.py", "noise.py"],
            ["expected.py"],
            low_budget_extra_file_waste=100,
            precision_delta_if_drop_last_summary=0.5,
        ),
        _make_result(
            ["noise.py", "expected.py"],
            ["expected.py"],
            low_budget_extra_file_waste=0,
            precision_delta_if_drop_last_summary=-0.5,
        ),
        _make_result(["other.py"], ["expected.py"]),
    ]

    avg_waste, avg_delta, cases = _low_budget_waste_summary(rows)

    assert cases == 2
    assert avg_waste == pytest.approx(50)
    assert avg_delta == pytest.approx(0.0)


def test_replacement_pair_diagnostics_parse_marginal_receipts() -> None:
    rows = _replacement_pair_diagnostics(
        receipts=[
            Receipt(
                path="src/noise.py",
                action="excluded",
                reason="marginal slot replaced by src/expected.py",
            )
        ],
        scored_map={
            "src/noise.py": {"rank": 1, "score": 300.0, "reasons": ["filename keyword match"]},
            "src/expected.py": {
                "rank": 5,
                "score": 260.0,
                "reasons": ["matched define: expected", "content keyword match (4)"],
            },
        },
        selected_tokens={"src/noise.py": 120},
    )

    assert rows == [{
        "displaced": "src/noise.py",
        "challenger": "src/expected.py",
        "displaced_score": 300.0,
        "challenger_score": 260.0,
        "challenger_rank": 5,
        "displaced_tokens": 120,
        "challenger_reasons": ["matched define: expected", "content keyword match (4)"],
        "displaced_reasons": ["filename keyword match"],
    }]


def test_same_scope_replacement_opportunities_find_token_neutral_stronger_miss() -> None:
    rows = _same_scope_replacement_opportunities(
        missed_expected=[{
            "path": "packages/vite/src/node/server/index.ts",
            "status": "compressed context cap reached",
            "rank": 12,
            "score": 240.0,
            "reasons": ["matched define: createServer", "content keyword match (4)"],
            "cap_block_diagnostic": {"candidate_tokens": 150},
        }],
        selected_noise=[{
            "path": "packages/vite/src/node/server/middleware.ts",
            "tokens": 180,
            "rank": 8,
            "score": 90.0,
            "reasons": ["filename keyword match"],
        }],
        scored_map={
            "packages/vite/src/node/server/index.ts": {
                "rank": 12,
                "score": 240.0,
                "reasons": ["matched define: createServer", "content keyword match (4)"],
                "estimated_tokens": 999,
            },
        },
    )

    assert rows == [{
        "missed": "packages/vite/src/node/server/index.ts",
        "selected_noise": "packages/vite/src/node/server/middleware.ts",
        "scope": "packages/vite/src/node/server",
        "missed_rank": 12,
        "noise_rank": 8,
        "missed_score": 240.0,
        "noise_score": 90.0,
        "missed_tokens": 150,
        "noise_tokens": 180,
        "token_delta": -30,
        "missed_evidence": 187.0,
        "noise_evidence": 34.5,
        "evidence_gain": 152.5,
        "missed_reasons": ["matched define: createServer", "content keyword match (4)"],
        "noise_reasons": ["filename keyword match"],
    }]


def test_same_scope_replacement_opportunities_ignore_unrelated_or_larger_miss() -> None:
    rows = _same_scope_replacement_opportunities(
        missed_expected=[{
            "path": "src/auth/session.py",
            "status": "compressed context cap reached",
            "rank": 9,
            "score": 250.0,
            "reasons": ["matched define: verify_session", "content keyword match (5)"],
        }],
        selected_noise=[{
            "path": "docs/session.md",
            "tokens": 300,
            "rank": 3,
            "score": 50.0,
            "reasons": ["filename keyword match"],
        }, {
            "path": "src/auth/cache.py",
            "tokens": 100,
            "rank": 4,
            "score": 50.0,
            "reasons": ["filename keyword match"],
        }],
        scored_map={
            "src/auth/session.py": {
                "rank": 9,
                "score": 250.0,
                "reasons": ["matched define: verify_session", "content keyword match (5)"],
                "estimated_tokens": 160,
            },
        },
    )

    assert rows == []


def test_plausibly_useful_selected_noise_flags_same_package_noise() -> None:
    rows = _plausibly_useful_selected_noise(
        selected_noise=[{
            "path": "packages/vite/src/node/server/middleware.ts",
            "tokens": 180,
            "rank": 8,
            "score": 90.0,
            "reasons": ["filename keyword match"],
        }, {
            "path": "docs/server.md",
            "tokens": 80,
            "rank": 2,
            "score": 120.0,
            "reasons": ["filename keyword match"],
        }],
        expected_set={"packages/vite/src/node/server/index.ts"},
        scored_map={},
    )

    assert rows == [{
        "path": "packages/vite/src/node/server/middleware.ts",
        "family": "source",
        "scope": "packages/vite/src/node/server",
        "workspace_package": "packages/vite",
        "rank": 8,
        "score": 90.0,
        "tokens": 180,
        "plausibility_reasons": [
            "same_or_related_scope_as_expected",
            "same_workspace_package_as_expected",
        ],
        "selection_reasons": ["filename keyword match"],
    }]


def test_label_audit_summary_estimates_plausible_unlabeled_tokens() -> None:
    summary = _label_audit_summary(
        selected_noise=[
            {"path": "packages/vite/src/node/server/middleware.ts", "tokens": 180},
            {"path": "docs/server.md", "tokens": 80},
        ],
        plausibly_useful=[
            {"path": "packages/vite/src/node/server/middleware.ts", "tokens": 180},
        ],
        packed_tokens=1000,
    )

    assert summary == {
        "selected_noise_count": 2,
        "selected_noise_tokens": 260,
        "plausibly_useful_count": 1,
        "plausibly_useful_tokens": 180,
        "audited_noise_tokens": 80,
        "adjusted_token_precision": 0.92,
    }


def test_benchmark_intent_profile_classifies_dependency_and_miss_families() -> None:
    profile = _benchmark_intent_profile(
        task="Upgrade Spring Boot and update Docker images",
        expected_files={"pom.xml", "src/test/java/acme/AppTests.java"},
        missed_expected=[
            {"path": "src/test/java/acme/AppTests.java"},
            {"path": "pom.xml"},
        ],
        selected_noise=[{"path": "src/main/java/acme/App.java", "family": "source"}],
    )

    assert profile["primary"] == "dependency_release"
    assert profile["expected_family_counts"] == {"config": 1, "test": 1}
    assert profile["missed_family_counts"] == {"config": 1, "test": 1}
    assert profile["selected_noise_family_counts"] == {"source": 1}
    assert "task:dependency_release:upgrade" in profile["signals"]


def test_owner_family_include_rank_and_package_diagnostics() -> None:
    expected = {
        "packages/vite/src/node/server/index.ts",
        "packages/vite/src/node/server/index.spec.ts",
        "docs/server.md",
    }
    selected = {
        "packages/vite/src/node/server/index.ts",
        "docs/server.md",
    }
    selected_modes = {
        "packages/vite/src/node/server/index.ts": "skeleton",
        "docs/server.md": "summary",
    }
    scored_map = {
        "packages/vite/src/node/server/index.ts": {"rank": 2},
        "packages/vite/src/node/server/index.spec.ts": {"rank": 9},
        "docs/server.md": {"rank": 21},
    }

    assert _owner_file_recall(selected_set=selected, expected_set=expected) == {
        "owner_files": ["packages/vite/src/node/server/index.ts"],
        "selected": 1,
        "total": 1,
        "recall": 1.0,
        "owner_family": "source",
    }
    assert _expected_family_recall(selected_set=selected, expected_set=expected) == {
        "docs": {"selected": 1.0, "expected": 1.0, "recall": 1.0},
        "source": {"selected": 1.0, "expected": 1.0, "recall": 1.0},
        "test": {"selected": 0.0, "expected": 1.0, "recall": 0.0},
    }
    assert _expected_include_mode_diagnostics(expected_set=expected, selected_modes=selected_modes) == {
        "selected_expected_count": 2,
        "expected_count": 3,
        "mode_counts": {"skeleton": 1, "summary": 1},
        "by_family": {"docs": {"summary": 1}, "source": {"skeleton": 1}},
        "source_code_block_rate": 1.0,
        "test_code_block_rate": 0.0,
        "summary_only_expected_rate": 0.5,
    }
    assert _expected_rank_distribution(expected, scored_map) == {
        "ranked_expected_count": 3,
        "unranked_expected_count": 0,
        "median": 9,
        "p90": 21,
        "min": 2,
        "max": 21,
        "buckets": {"1_3": 1, "4_8": 0, "9_20": 1, "21_plus": 1},
    }
    assert _package_boundary_diagnostics(
        selected_paths=[
            "packages/vite/src/node/server/index.ts",
            "packages/playground/src/main.ts",
            "docs/server.md",
        ],
        expected_set=expected,
    ) == {
        "expected_packages": ["docs", "packages/vite"],
        "selected_expected_package_files": 2,
        "selected_cross_package_files": 1,
        "selected_package_match_rate": 0.667,
    }


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
        low_budget_extra_file_waste=120,
        precision_delta_if_drop_last_summary=0.08,
    )
    result.case.task = "real-api: fix auth token expiry"
    result.case.task_type = "backend-api"

    content = _public_benchmark_markdown([result], suite="real repos", version="0.3.0")

    assert "AgentPack Public Benchmark Table" in content
    assert "real-api" in content
    assert "fix auth token expiry" in content
    assert "avg recall" in content
    assert "avg last-summary waste" in content
    assert "+8.0%" in content
    assert "| Repo / suite | Task | Type | Mode | Budget | Packed tokens | Recall | Cand R@50 | Cand P@3 |" in content
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


def test_benchmark_public_suite_reproduce_maps_to_public_repo_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "public-repos.toml").write_text(
        "[[repos]]\nname='empty'\nurl='x'\nsample_history=1\n",
        encoding="utf-8",
    )
    mocked = _make_result(["a.py"], ["a.py"], noise_pct=0.0)
    mocked.case.task = "repo: fix thing"
    with patch(
        "agentpack.commands.benchmark._load_public_repo_specs",
        return_value=[SimpleNamespace(name="repo", cases=[], sample_history=1)],
    ), patch("agentpack.commands.benchmark._run_public_repo_suite", return_value=[mocked]) as run_suite, patch(
        "agentpack.commands.benchmark._write_public_benchmark_table"
    ) as write_table:
        result = CliRunner().invoke(app, ["benchmark", "--public-suite", "--reproduce", "v0.3.20"])

    assert result.exit_code == 0, result.output
    assert "Public suite" in result.output
    assert run_suite.called
    assert write_table.called


def test_filter_public_repo_specs_by_repo_and_task_type() -> None:
    specs = [
        PublicRepoSpec(
            name="gin",
            url="https://example.test/gin.git",
            sample_history=20,
            task_type="go-service",
            cases=[
                PublicRepoCase(
                    commit="abc",
                    task="fix go",
                    expected_files=["a.go"],
                    task_type="go-service",
                )
            ],
        ),
        PublicRepoSpec(
            name="vite",
            url="https://example.test/vite.git",
            sample_history=20,
            task_type="typescript",
            cases=[
                PublicRepoCase(
                    commit="def",
                    task="fix ts",
                    expected_files=["a.ts"],
                    task_type="typescript",
                )
            ],
        ),
    ]

    filtered = _filter_public_repo_specs(
        specs,
        repo_filter="gin,vite",
        task_type_filter="go-service",
    )

    assert [spec.name for spec in filtered] == ["gin"]
    assert filtered[0].sample_history == 20
    assert [case.task for case in filtered[0].cases] == ["fix go"]


def test_write_results_jsonl_uses_benchmark_record_shape(tmp_path: Path) -> None:
    result = _make_result(["a.py"], ["a.py"], noise_pct=0.0)
    result.case.task_type = "python"
    out = _write_results_jsonl(tmp_path / "bench" / "results.jsonl", [result])

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["task"] == result.case.task
    assert rows[0]["task_type"] == "python"
    assert rows[0]["expected_files"] == ["a.py"]
    assert rows[0]["selected_paths"] == ["a.py"]
    assert rows[0]["recall"] == 1.0
    assert rows[0]["token_precision"] == 1.0
    assert rows[0]["misses"] == []


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
    assert cases[0].mode == "balanced"
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
        'sample_history = 12\n'
        'task_type = "python-cli"\n'
        'mode = "balanced"\n'
        'budget = 2000\n'
        'include_globs = ["src/**/*.py", "tests/**/*.py"]\n'
        'exclude_globs = ["docs/**"]\n'
        'max_changed_files = 6\n\n'
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
    assert specs[0].sample_history == 12
    assert specs[0].include_globs == ["src/**/*.py", "tests/**/*.py"]
    assert specs[0].exclude_globs == ["docs/**"]
    assert specs[0].max_changed_files == 6
    assert specs[0].cases[0].commit == "abc123"
    assert specs[0].cases[0].expected_files == ["src/click/termui.py", "tests/test_termui.py"]


def test_load_public_repo_specs_defaults_to_balanced_mode(tmp_path: Path) -> None:
    f = tmp_path / "public.toml"
    f.write_text(
        '[[repos]]\n'
        'name = "repo"\n'
        'url = "https://example.test/repo.git"\n\n'
        '[[repos.cases]]\n'
        'commit = "abc123"\n'
        'task = "fix bug"\n'
        'expected_files = ["src/app.ts"]\n',
        encoding="utf-8",
    )

    specs = _load_public_repo_specs(f)

    assert specs[0].mode == "balanced"
    assert specs[0].cases[0].mode == "balanced"


def test_sample_public_history_cases_uses_commit_subject_and_changed_files(tmp_path: Path) -> None:
    from agentpack.commands import benchmark as benchmark_mod

    spec = benchmark_mod.PublicRepoSpec(
        name="repo",
        url="https://example.test/repo.git",
        ref="main",
        sample_history=2,
        task_type="typescript",
        mode="balanced",
        budget=3000,
        include_globs=["src/**/*.ts", "tests/*.ts", "tests/**/*.ts"],
    )

    def fake_git_lines(_cwd: Path, args: list[str]) -> list[str]:
        if args[0] == "log":
            return [
                "c1\x00Fix auth client",
                "c2\x00Update docs only",
                "c3\x00Fix parser",
            ]
        if args[-1] == "c1":
            return ["src/auth/client.ts", "tests/auth.test.ts"]
        if args[-1] == "c2":
            return ["docs/readme.md"]
        if args[-1] == "c3":
            return ["src/parser/index.ts"]
        return []

    with patch("agentpack.commands.benchmark._git_lines", side_effect=fake_git_lines), \
         patch("agentpack.commands.benchmark._git_stdout", return_value="parent"), \
         patch("agentpack.commands.benchmark._public_path_exists_at_commit", return_value=True):
        cases = _sample_public_history_cases(tmp_path, spec)

    assert [case.commit for case in cases] == ["c1", "c3"]
    assert cases[0].task == "Fix auth client"
    assert cases[0].expected_files == ["src/auth/client.ts", "tests/auth.test.ts"]
    assert cases[0].task_type == "typescript"
    assert cases[0].mode == "balanced"
    assert cases[0].budget == 3000


def test_public_commit_changed_files_filters_noise_added_files_and_large_commits(tmp_path: Path) -> None:
    def exists_in_parent(_repo: Path, _commit: str, path: str) -> bool:
        return path != "src/new.py"

    with patch("agentpack.commands.benchmark._git_stdout", return_value="parent"), \
         patch("agentpack.commands.benchmark._public_path_exists_at_commit", side_effect=exists_in_parent), \
         patch("agentpack.commands.benchmark._git_lines", return_value=[
             "src/app.py",
             "src/new.py",
             "docs/readme.md",
             "package-lock.json",
         ]):
        files = _public_commit_changed_files(
            tmp_path,
            "abc123",
            include_globs=["src/**/*.py", "src/*.py"],
            exclude_globs=["docs/**"],
            max_changed_files=2,
        )

    assert files == ["src/app.py"]


def test_ensure_public_repo_clone_uses_full_shallow_clone(tmp_path: Path) -> None:
    spec = PublicRepoSpec(name="repo", url="https://example.test/repo.git", ref="main")

    with patch("agentpack.commands.benchmark._run_git") as run_git:
        repo = _ensure_public_repo_clone(spec, tmp_path / "cache", depth=25)

    assert repo == tmp_path / "cache" / "repo"
    clone_args = run_git.call_args_list[0].args[1]
    assert clone_args == [
        "clone",
        "--quiet",
        "--depth",
        "25",
        "https://example.test/repo.git",
        str(repo),
    ]
    assert "--filter=blob:none" not in clone_args
    assert any(call.args[1] == ["checkout", "--quiet", "main"] for call in run_git.call_args_list)
    assert any(call.args[1] == ["reset", "--hard", "--quiet", "main"] for call in run_git.call_args_list)
    assert any(call.args[1] == ["clean", "-ffd", "--quiet"] for call in run_git.call_args_list)


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
    assert case_arg.task == "fix prompt"
    assert case_arg.task_type == "python-cli"
    assert case_arg.budget == 1200
    assert [call.args for call in ensure_commit.call_args_list] == [
        (tmp_path / "cache", "abc123"),
        (tmp_path / "cache", "parent123"),
    ]
    git_stdout.assert_called_once_with(tmp_path / "cache", ["rev-parse", "abc123^"])
    copytree.assert_called_once()
    assert any(call.args[1] == ["checkout", "--force", "--quiet", "parent123"] for call in run_git.call_args_list)
    assert any(call.args[1] == ["reset", "--hard", "--quiet", "parent123"] for call in run_git.call_args_list)
    assert any(call.args[1] == ["clean", "-ffd", "--quiet"] for call in run_git.call_args_list)


def test_run_public_repo_suite_checkout_error_names_case(tmp_path: Path) -> None:
    from agentpack.commands import benchmark as benchmark_mod

    spec = benchmark_mod.PublicRepoSpec(
        name="vite",
        url="https://example.test/vite.git",
        cases=[
            benchmark_mod.PublicRepoCase(
                commit="abc123",
                task="fix vite",
                expected_files=["packages/vite/src/node/server/index.ts"],
            ),
        ],
    )
    checkout_error = subprocess.CalledProcessError(
        1,
        ["git", "checkout", "--force", "--quiet", "parent123"],
        stderr="pathspec parent123 did not match any file(s) known to git",
    )

    with patch("agentpack.commands.benchmark._ensure_public_repo_clone", return_value=tmp_path / "cache"), \
         patch("agentpack.commands.benchmark._ensure_git_commit"), \
         patch("agentpack.commands.benchmark._git_stdout", return_value="parent123"), \
         patch("agentpack.commands.benchmark._run_git", side_effect=checkout_error), \
         patch("agentpack.commands.benchmark.shutil.copytree"):
        with pytest.raises(RuntimeError) as excinfo:
            _run_public_repo_suite(tmp_path, [spec], cache_dir=tmp_path / "cache")

    message = str(excinfo.value)
    assert "repo=vite" in message
    assert "commit=abc123" in message
    assert "parent=parent123" in message
    assert "git checkout --force --quiet parent123" in message
    assert "pathspec parent123" in message


# ---------------------------------------------------------------------------
# _persist_result
# ---------------------------------------------------------------------------

def test_persist_result_writes_jsonl(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    r = _make_result(
        ["a.py", "b.py"],
        ["a.py"],
        rank_at_k=3,
        candidate_recall_at_20=0.2,
        candidate_recall_at_50=0.5,
        candidate_recall_at_100=1.0,
        candidate_precision_at_3=0.333,
        candidate_precision_at_5=0.4,
        low_budget_extra_file_waste=100,
        precision_delta_if_drop_last_summary=0.125,
        expected_token_coverage=0.5,
        selected_family_tokens={"source": 100, "docs": 50},
        selected_family_waste_tokens={"docs": 50},
        reason_family_precision={"filename": {"selected": 2.0, "expected": 1.0, "precision": 0.5}},
        failure_type_counts={"EXPECTED_SKIPPED": 1},
        noise_pct=30.0,
        random_f1=0.2,
        top_candidates=[{
            "path": "a.py",
            "rank": 1,
            "score": 10.0,
            "family": "source",
            "selected": True,
            "expected": True,
            "reasons": ["symbol keyword match"],
        }],
        selection_diagnostics={
            "selected_noise": [{
                "path": "b.py",
                "family": "source",
                "tokens": 100,
                "mode": None,
                "rank": 2,
                "score": 5.0,
                "reasons": ["filename keyword match"],
            }],
            "selected_noise_family_tokens": {"source": 100},
            "expected_ranked_not_selected": 0,
            "missed_expected_count": 0,
        },
    )
    _persist_result(tmp_path, r)

    out = tmp_path / ".agentpack" / "benchmark_results.jsonl"
    assert out.exists()
    record = json.loads(out.read_text().strip())
    assert record["task"] == "t"
    assert record["task_type"] == "general"
    assert record["after_ignore_tokens"] == 8000
    assert "saving_pct_honest" in record
    assert record["rank_at_k"] == 3
    assert record["candidate_recall_at_20"] == pytest.approx(0.2)
    assert record["candidate_recall_at_50"] == pytest.approx(0.5)
    assert record["candidate_recall_at_100"] == pytest.approx(1.0)
    assert record["candidate_precision_at_3"] == pytest.approx(0.333)
    assert record["candidate_precision_at_5"] == pytest.approx(0.4)
    assert record["low_budget_extra_file_waste"] == 100
    assert record["precision_delta_if_drop_last_summary"] == pytest.approx(0.125)
    assert record["expected_token_coverage"] == pytest.approx(0.5)
    assert record["selected_family_tokens"] == {"source": 100, "docs": 50}
    assert record["selected_family_waste_tokens"] == {"docs": 50}
    assert record["reason_family_precision"]["filename"]["precision"] == pytest.approx(0.5)
    assert record["failure_type_counts"] == {"EXPECTED_SKIPPED": 1}
    assert record["noise_pct"] == pytest.approx(30.0)
    assert record["token_precision"] == pytest.approx(0.7)
    assert record["random_f1"] == pytest.approx(0.2)
    assert record["top_candidates"][0]["path"] == "a.py"
    assert record["selection_diagnostics"]["selected_noise"][0]["path"] == "b.py"


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


def test_write_anonymous_benchmark_report_contains_no_source_paths(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".agentpack" / "benchmark.toml").write_text(
        '[[cases]]\ntask = "fix bug"\nexpected_files = ["src/app.py"]\n',
        encoding="utf-8",
    )
    (tmp_path / ".agentpack" / "benchmark_results.jsonl").write_text(
        json.dumps({"recall": 1.0, "token_precision": 0.5, "misses": []}) + "\n",
        encoding="utf-8",
    )

    report_md, report_json = _write_anonymous_benchmark_report(tmp_path)

    markdown = report_md.read_text(encoding="utf-8")
    data = json.loads(report_json.read_text(encoding="utf-8"))
    assert "No source code uploaded: true" in markdown
    assert "src/app.py" not in markdown
    assert data["cases"] == 1
    assert data["recall"] == 1.0
    assert data["source_paths_included"] is False


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
        {"task": "refactor db", "mode": "balanced"},
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
    sf.reasons = ["filename keyword match"]
    sf.include_mode = "summary"
    sf.score = 1.0

    scored_fi = MagicMock()
    scored_fi.path = "src/foo.py"

    plan = MagicMock()
    plan.selected = [sf]
    plan.scan_result = scan_result
    plan.all_changed = {"src/foo.py"}
    plan.phase_times = {"scan": 0.1, "rank": 0.05}
    plan.scored = [(scored_fi, 1.0, ["keyword_match"])]
    plan.receipts = []
    plan.summaries = {}
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
    assert result.expected_token_coverage is not None
    assert result.selected_family_tokens
    assert result.reason_family_precision
    assert result.random_f1 is not None


def test_run_case_records_miss_diagnostics(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix bug", mode="balanced", expected_files=["src/missing.py"])
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

    assert result.top_candidates[0]["path"] == "src/missing.py"
    assert result.top_candidates[0]["expected"] is True
    assert result.selection_diagnostics["selected_noise"][0]["path"] == "src/foo.py"

    miss = result.missed_expected[0]
    assert miss["path"] == "src/missing.py"
    assert miss["status"] == "budget exhausted"
    assert miss["failure_type"] == "EXPECTED_SKIPPED"
    assert miss["family"] == "source"
    assert miss["rank"] == 1
    assert miss["score"] == 42.0
    assert miss["reasons"] == ["filename keyword match"]
    assert miss["basis"] == mock_plan.changed_files_source
    assert miss["would_select_with_one_more_slot"] is True
    assert miss["score_delta_vs_last_selected"] == pytest.approx(41.0)
    assert miss["selected_noise_file_that_beat_expected"] is None
    assert miss["cap_block_diagnostic"] is None


def test_run_case_records_cap_block_diagnostic(tmp_path: Path) -> None:
    case = BenchmarkCase(task="fix config", mode="balanced", expected_files=["src/missing.py"])
    mock_plan = _make_mock_plan()
    mock_plan.receipts = [Receipt(path="src/missing.py", action="excluded", reason="compressed context cap reached")]

    missing_fi = MagicMock()
    missing_fi.path = "src/missing.py"
    missing_fi.estimated_tokens = 200
    missing_fi.ignored = False
    missing_fi.binary = False
    mock_plan.scan_result.packable = mock_plan.scan_result.packable + [missing_fi]
    mock_plan.scan_result.all_files = mock_plan.scan_result.all_files + [missing_fi]
    mock_plan.scored = mock_plan.scored + [(
        missing_fi,
        220.0,
        ["config file", "content keyword match (3)", "matched define: missing_config"],
    )]
    mock_plan.summaries = {
        "src/missing.py": {
            "summary": "Missing config owner.",
            "symbols": [{"signature": "def missing_config(): ..."}],
        }
    }

    with patch("agentpack.application.pack_service.PackPlanner") as MockPlanner, \
         patch("agentpack.application.pack_service._sf_tokens", return_value=50):
        MockPlanner.return_value.plan.return_value = mock_plan
        result = _run_case(tmp_path, case)

    diagnostic = result.missed_expected[0]["cap_block_diagnostic"]
    assert diagnostic["candidate_mode"] == "skeleton"
    assert diagnostic["candidate_has_strong_evidence"] is True
    assert diagnostic["replaceable_selected_tokens"] == 50
    assert diagnostic["replaceable_selected"][0]["path"] == "src/foo.py"
    assert diagnostic["block_reason"] == "replacement appears feasible"


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
    assert _is_test_path("src/test/java/org/example/AppTests.java")
    assert _is_test_path("frontend/button.test.tsx")
    assert _is_test_path("context_test.go")
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
    result = subprocess.CompletedProcess(
        args=["agent"],
        returncode=0,
        stdout="exec_command rg auth\nhello world",
        stderr="apply_patch done",
    )

    assert _process_output_tokens(result) >= 1
    assert _estimate_agent_tool_calls(result) >= 2
    assert _estimate_token_cost(1_000_000, 2.5) == 2.5
    assert _estimate_token_cost(1000, 0.0) == 0.0


def test_time_to_first_expected_file_uses_mtime_delta(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('ok')\n", encoding="utf-8")
    start = target.stat().st_mtime - 2.0

    delta = _time_to_first_expected_file(tmp_path, ["src/app.py"], start)

    assert delta == pytest.approx(2.0, abs=0.1)


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
    assert result.agent_tool_calls >= 0
    assert result.time_to_first_expected_file_s is None
    assert result.agentpack_noise == []


def test_e2e_hybrid_prompt_combines_grep_and_lite(tmp_path: Path) -> None:
    case = E2ECase(name="hybrid", repo=tmp_path, task="fix auth", test_command="pytest")

    with patch("agentpack.commands.benchmark._grep_context", return_value="grep-hit"), \
         patch("agentpack.commands.benchmark._agentpack_lite_context", return_value="lite-map"):
        prompt = _e2e_prompt(case, "hybrid", tmp_path)

    assert "grep-hit" in prompt
    assert "lite-map" in prompt


def test_e2e_ab_metrics_reports_saved_tool_tokens_cost_time_and_success(tmp_path: Path) -> None:
    records = [
        {
            "strategy": "no-context",
            "passed": False,
            "input_tokens": 1000,
            "agent_output_tokens": 500,
            "estimated_total_cost_usd": 0.03,
            "duration_s": 60,
            "agent_tool_calls": 12,
            "time_to_first_expected_file_s": 40,
            "expected_files_touched": [],
            "missing_expected_edits": ["src/app.py"],
        },
        {
            "strategy": "agentpack",
            "passed": True,
            "input_tokens": 1200,
            "agent_output_tokens": 100,
            "estimated_total_cost_usd": 0.02,
            "duration_s": 45,
            "agent_tool_calls": 6,
            "time_to_first_expected_file_s": 10,
            "expected_files_touched": ["src/app.py"],
            "missing_expected_edits": [],
            "agentpack_noise": ["unexpected README"],
        },
    ]

    metrics = _e2e_ab_metrics(records, baseline="no-context", treatment="agentpack")
    markdown = _e2e_ab_markdown(records, baseline="no-context", treatment="agentpack", source=tmp_path / "results.jsonl")

    assert metrics["deltas"]["success_rate_pp"] == pytest.approx(100.0)
    assert metrics["deltas"]["tool_calls_saved"] == pytest.approx(6.0)
    assert metrics["deltas"]["token_cost_saved_usd"] == pytest.approx(0.01)
    assert metrics["deltas"]["time_to_first_correct_file_saved_s"] == pytest.approx(30.0)
    assert metrics["treatment"]["noise_rate"] == pytest.approx(1.0)
    assert "tool calls" in markdown
    assert "time to first correct file" in markdown
    assert "AgentPack noise cases" in markdown


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
