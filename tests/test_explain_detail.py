from __future__ import annotations

from types import SimpleNamespace

from agentpack.commands.explain import _noise_report, _print_budget_plan, _resolve_signal_weight
from agentpack.core.models import SelectedFile
from agentpack.core.config import ScoringWeights


_WEIGHTS = ScoringWeights(
    modified=100,
    staged=90,
    filename_keyword=80,
    symbol_keyword=70,
    content_keyword_per_hit=10,
    content_keyword_max=60,
    direct_dep=50,
    reverse_dep=40,
    related_test=35,
    config_file=25,
    recently_modified=20,
    large_unrelated_penalty=-50,
)


def test_modified_signal() -> None:
    assert _resolve_signal_weight("modified", _WEIGHTS) == 100.0


def test_staged_signal() -> None:
    assert _resolve_signal_weight("staged", _WEIGHTS) == 90.0


def test_filename_keyword_signal() -> None:
    assert _resolve_signal_weight("filename keyword match", _WEIGHTS) == 80.0


def test_symbol_keyword_signal() -> None:
    assert _resolve_signal_weight("symbol keyword match", _WEIGHTS) == 70.0


def test_content_keyword_single_hit() -> None:
    assert _resolve_signal_weight("content keyword match (1)", _WEIGHTS) == 10.0


def test_content_keyword_many_hits_capped() -> None:
    # 10 hits × 10 = 100, but max is 60
    assert _resolve_signal_weight("content keyword match (10)", _WEIGHTS) == 60.0


def test_content_keyword_exact_cap_boundary() -> None:
    # 6 hits × 10 = 60 = max
    assert _resolve_signal_weight("content keyword match (6)", _WEIGHTS) == 60.0


def test_direct_dep_signal() -> None:
    assert _resolve_signal_weight("direct dependency of changed file", _WEIGHTS) == 50.0


def test_reverse_dep_signal() -> None:
    assert _resolve_signal_weight("reverse dependency", _WEIGHTS) == 40.0


def test_related_test_signal() -> None:
    assert _resolve_signal_weight("has related tests", _WEIGHTS) == 35.0


def test_config_file_signal() -> None:
    assert _resolve_signal_weight("config file", _WEIGHTS) == 25.0


def test_recently_modified_signal() -> None:
    assert _resolve_signal_weight("recently modified", _WEIGHTS) == 20.0


def test_large_unrelated_penalty() -> None:
    assert _resolve_signal_weight("large/unrelated file", _WEIGHTS) == -50.0
    assert _resolve_signal_weight("large unrelated file", _WEIGHTS) == -50.0


def test_unknown_reason_returns_zero() -> None:
    assert _resolve_signal_weight("some unknown signal", _WEIGHTS) == 0.0


def test_case_insensitive_matching() -> None:
    assert _resolve_signal_weight("Modified", _WEIGHTS) == 100.0
    assert _resolve_signal_weight("STAGED", _WEIGHTS) == 90.0
    assert _resolve_signal_weight("Filename Keyword Match", _WEIGHTS) == 80.0


def test_noise_report_names_generic_terms() -> None:
    plan = SimpleNamespace(
        keyword_plan=SimpleNamespace(
            term_stats={
                "pack": {"weight": 0.25, "rarity": 0.1, "kind": "generic", "good_runs": 0, "bad_runs": 2},
                "stats": {"weight": 0.25, "rarity": 0.2, "kind": "generic", "good_runs": 0, "bad_runs": 2},
            },
            phrase_stats={
                "pack stats": {"weight": 0.35, "rarity": 0.3, "kind": "phrase", "good_runs": 0, "bad_runs": 1},
            },
        ),
        selected=[
            SimpleNamespace(include_mode="summary", reasons=["filename keyword match"]),
            SimpleNamespace(include_mode="summary", reasons=["filename keyword match"]),
        ],
        receipts=[
            SimpleNamespace(action="excluded", reason="compressed context cap reached"),
            SimpleNamespace(action="excluded", reason="summary score below floor"),
        ],
    )

    report = "\n".join(_noise_report("fix pack stats noise", plan))

    assert "generic terms:" in report
    assert "pack" in report
    assert "stats" in report
    assert "ambiguous terms:" in report
    assert "excluded by summary cap: 1" in report
    assert "Keep standard balanced mode" in report
    assert "Rewrite example:" in report


def test_print_term_weights_renders_tables(capsys) -> None:
    from agentpack.commands.explain import _print_term_weights

    plan = SimpleNamespace(
        keyword_plan=SimpleNamespace(
            term_stats={
                "signup": {"weight": 1.2, "rarity": 0.8, "kind": "positive", "good_runs": 2, "bad_runs": 0},
            },
            phrase_stats={
                "signup gate": {"weight": 1.3, "rarity": 0.9, "kind": "positive", "good_runs": 2, "bad_runs": 0},
            },
        )
    )

    _print_term_weights(plan)

    out = capsys.readouterr().out
    assert "Task term weights" in out
    assert "Task phrase weights" in out
    assert "signup gate" in out


def test_budget_plan_prints_modes_and_value(capsys) -> None:
    plan = SimpleNamespace(
        budget=1000,
        selected=[
            SelectedFile(path="a.py", score=200, include_mode="diff", reasons=["modified"], content="+x"),
            SelectedFile(path="b.py", score=100, include_mode="skeleton", reasons=["filename keyword match"], content="def run(): ..."),
        ],
    )

    _print_budget_plan(plan)

    out = capsys.readouterr().out
    assert "Budget plan" in out
    assert "diff" in out
    assert "skeleton" in out
    assert "value/tok" in out
