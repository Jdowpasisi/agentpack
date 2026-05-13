from __future__ import annotations

from types import SimpleNamespace

from agentpack.commands.explain import _noise_report, _resolve_signal_weight
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
        selected=[
            SimpleNamespace(include_mode="summary", reasons=["filename keyword match"]),
            SimpleNamespace(include_mode="summary", reasons=["filename keyword match"]),
        ],
        receipts=[
            SimpleNamespace(action="excluded", reason="summary cap reached"),
            SimpleNamespace(action="excluded", reason="summary score below floor"),
        ],
    )

    report = "\n".join(_noise_report("fix pack stats noise", plan))

    assert "generic terms:" in report
    assert "pack" in report
    assert "stats" in report
    assert "excluded by summary cap: 1" in report
    assert "Try `--mode minimal`" in report
