"""Tests for Features 1-3: knowledge file scoring, boost_paired_tests, and git churn."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agentpack.analysis.ranking import (
    _is_knowledge_file,
    boost_paired_tests,
    score_files,
)
from agentpack.core.config import ScoringWeights
from agentpack.core.models import FileInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fi(path: str, tokens: int = 100, language: str = "python") -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path("/nonexistent") / path,
        size_bytes=tokens * 4,
        estimated_tokens=tokens,
        language=language,
    )


# ===========================================================================
# Feature 1: Knowledge file scoring
# ===========================================================================

class TestIsKnowledgeFile:
    def test_decisions_md(self):
        assert _is_knowledge_file("DECISIONS.md")

    def test_decisions_md_nested(self):
        assert _is_knowledge_file("docs/DECISIONS.md")

    def test_adr_md(self):
        assert _is_knowledge_file("ADR.md")

    def test_architecture_md(self):
        assert _is_knowledge_file("architecture.md")

    def test_contributing_md(self):
        assert _is_knowledge_file("CONTRIBUTING.md")

    def test_design_md(self):
        assert _is_knowledge_file("design.md")

    def test_technical_md(self):
        assert _is_knowledge_file("technical.md")

    def test_tradeoffs_md(self):
        assert _is_knowledge_file("tradeoffs.md")

    def test_rfc_md(self):
        assert _is_knowledge_file("rfc.md")

    def test_proposal_md(self):
        assert _is_knowledge_file("proposal.md")

    def test_adr_numbered_hyphen(self):
        assert _is_knowledge_file("adr-001-use-postgres.md")

    def test_adr_numbered_underscore(self):
        assert _is_knowledge_file("docs/adr_002_auth_service.md")

    def test_adr_numbered_no_sep(self):
        assert _is_knowledge_file("adr001.md")

    def test_md_in_adr_dir(self):
        assert _is_knowledge_file("docs/adr/001-use-postgres.md")

    def test_md_in_adrs_dir(self):
        assert _is_knowledge_file("adrs/002-caching-strategy.md")

    def test_md_in_decisions_dir(self):
        assert _is_knowledge_file("decisions/001-pick-db.md")

    def test_md_in_rfcs_dir(self):
        assert _is_knowledge_file("rfcs/001-feature.md")

    def test_md_in_proposals_dir(self):
        assert _is_knowledge_file("proposals/001-new-api.md")

    def test_md_in_design_dir(self):
        assert _is_knowledge_file("design/overview.md")

    def test_non_md_decisions(self):
        # DECISIONS.txt is NOT a knowledge file
        assert not _is_knowledge_file("DECISIONS.txt")

    def test_non_md_adr_dir(self):
        # Non-.md in adr dir is not a knowledge file
        assert not _is_knowledge_file("docs/adr/notes.txt")

    def test_unrelated_file(self):
        assert not _is_knowledge_file("src/auth/session.py")

    def test_readme_not_matched(self):
        # README is not in our knowledge names
        assert not _is_knowledge_file("README.md")


def test_knowledge_file_scoring():
    """DECISIONS.md and docs/adr/001-use-postgres.md get knowledge/architecture doc reason."""
    files = [
        _fi("DECISIONS.md"),
        _fi("docs/adr/001-use-postgres.md"),
        _fi("src/auth/session.py"),
    ]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=set(),
    )
    scores = {s[0].path: (s[1], s[2]) for s in scored}

    decisions_score, decisions_reasons = scores["DECISIONS.md"]
    assert decisions_score > 0
    assert any("knowledge/architecture doc" in r for r in decisions_reasons)

    adr_score, adr_reasons = scores["docs/adr/001-use-postgres.md"]
    assert adr_score > 0
    assert any("knowledge/architecture doc" in r for r in adr_reasons)

    # Regular source file should NOT get the knowledge reason
    src_score, src_reasons = scores["src/auth/session.py"]
    assert not any("knowledge/architecture doc" in r for r in src_reasons)


def test_knowledge_file_outscores_plain_source():
    """DECISIONS.md with no other signals should outscore a plain unreferenced source file."""
    files = [
        _fi("DECISIONS.md"),
        _fi("src/utils.py"),
    ]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=set(),
    )
    scores = {s[0].path: s[1] for s in scored}
    assert scores["DECISIONS.md"] > scores["src/utils.py"]


def test_knowledge_weight_configurable():
    """Custom knowledge_file weight is respected."""
    files = [_fi("architecture.md")]
    w = ScoringWeights(knowledge_file=999)
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=set(),
        weights=w,
    )
    assert scored[0][1] >= 999


# ===========================================================================
# Feature 2: boost_paired_tests
# ===========================================================================

class TestBoostPairedTests:
    def test_test_paired_with_high_scoring_source_gets_boost(self):
        """Test file paired with a high-scoring source file gets the related_test boost."""
        w = ScoringWeights()
        # Source file has high score (changed), test file has no prior boost
        source = _fi("src/auth/session.py")
        test_file = _fi("tests/test_session.py")

        # Score: source high (100 from modified), test low (0)
        pre_scored: list[tuple[FileInfo, float, list[str]]] = [
            (source, 100.0, ["modified"]),
            (test_file, 0.0, []),
        ]

        result = boost_paired_tests(pre_scored, weights=w)
        result_map = {fi.path: (score, reasons) for fi, score, reasons in result}

        test_score, test_reasons = result_map["tests/test_session.py"]
        assert test_score >= w.related_test
        assert any("test for high-scoring" in r for r in test_reasons)

    def test_already_boosted_test_not_double_boosted(self):
        """Test file already boosted by changed_paths is not boosted again."""
        w = ScoringWeights()
        source = _fi("src/auth/session.py")
        test_file = _fi("tests/test_session.py")

        pre_scored: list[tuple[FileInfo, float, list[str]]] = [
            (source, 100.0, ["modified"]),
            (test_file, w.related_test, [f"test for src/auth/session.py"]),
        ]

        result = boost_paired_tests(pre_scored, weights=w)
        result_map = {fi.path: (score, reasons) for fi, score, reasons in result}

        test_score, test_reasons = result_map["tests/test_session.py"]
        # Score should be unchanged (already boosted)
        assert test_score == w.related_test
        # Should not have the "high-scoring" reason
        assert not any("high-scoring" in r for r in test_reasons)

    def test_test_for_low_scoring_source_not_boosted(self):
        """Test file whose source scores below the median is not boosted."""
        w = ScoringWeights()
        # Many high-scoring sources and one low source
        high_sources = [(_fi(f"src/module{i}.py"), 100.0, ["modified"]) for i in range(10)]
        low_source = (_fi("src/lowscore.py"), 0.0, [])
        test_for_low = (_fi("tests/test_lowscore.py"), 0.0, [])

        pre_scored = high_sources + [low_source, test_for_low]
        result = boost_paired_tests(pre_scored, weights=w)
        result_map = {fi.path: (score, reasons) for fi, score, reasons in result}

        test_score, test_reasons = result_map["tests/test_lowscore.py"]
        # Low-score source is below median, test should not be boosted
        assert not any("high-scoring" in r for r in test_reasons)

    def test_no_non_test_files_returns_unchanged(self):
        """If there are no non-test files, return scored unchanged."""
        w = ScoringWeights()
        test_file = _fi("tests/test_session.py")
        pre_scored: list[tuple[FileInfo, float, list[str]]] = [
            (test_file, 0.0, []),
        ]
        result = boost_paired_tests(pre_scored, weights=w)
        assert result == pre_scored

    def test_empty_input_returns_empty(self):
        result = boost_paired_tests([])
        assert result == []

    def test_reasons_list_immutability(self):
        """boost_paired_tests should not mutate the original reasons list."""
        w = ScoringWeights()
        source = _fi("src/auth/session.py")
        test_file = _fi("tests/test_session.py")

        original_reasons: list[str] = []
        pre_scored: list[tuple[FileInfo, float, list[str]]] = [
            (source, 100.0, ["modified"]),
            (test_file, 0.0, original_reasons),
        ]

        boost_paired_tests(pre_scored, weights=w)
        # The original reasons list should NOT have been mutated
        assert original_reasons == []


def test_boost_paired_tests_integrated_with_score_files():
    """score_files + boost_paired_tests: test file with no changed source gets boosted
    when the source scores high via keyword matching."""
    w = ScoringWeights()
    files = [
        _fi("src/auth/session.py"),
        _fi("tests/test_session.py"),
    ]
    # "auth" and "session" match the source filename but test is not in changed_paths
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"auth", "session"},
        weights=w,
    )
    scored = boost_paired_tests(scored, weights=w)

    result_map = {fi.path: (score, reasons) for fi, score, reasons in scored}
    src_score, _ = result_map["src/auth/session.py"]
    test_score, test_reasons = result_map["tests/test_session.py"]

    assert src_score > 0, "Source should have scored from keyword match"
    assert any("high-scoring" in r for r in test_reasons), (
        f"Expected test to be boosted, got reasons: {test_reasons}"
    )


# ===========================================================================
# Feature 3: Git churn score
# ===========================================================================

class TestFileChurnCounts:
    def test_returns_empty_for_non_git_repo(self, tmp_path):
        from agentpack.core import git
        result = git.file_churn_counts(tmp_path)
        assert result == {}

    def test_parses_git_log_output(self):
        """Mock git log output and verify counts are computed correctly."""
        from agentpack.core import git

        fake_output = "\n".join([
            "",  # empty line from --format=
            "src/auth/session.py",
            "src/auth/token.py",
            "",
            "src/auth/session.py",
            "src/billing/invoice.py",
            "",
            "src/auth/session.py",
        ])

        with patch.object(git, "_run", return_value=fake_output):
            result = git.file_churn_counts(Path("/fake/repo"))

        assert result["src/auth/session.py"] == 3
        assert result["src/auth/token.py"] == 1
        assert result["src/billing/invoice.py"] == 1

    def test_returns_empty_when_git_unavailable(self, tmp_path):
        from agentpack.core import git
        with patch.object(git, "_run", return_value=None):
            result = git.file_churn_counts(tmp_path)
        assert result == {}

    def test_ignores_blank_lines(self):
        from agentpack.core import git
        fake_output = "\n\n  \n  src/foo.py  \n\n"
        with patch.object(git, "_run", return_value=fake_output):
            result = git.file_churn_counts(Path("/fake/repo"))
        assert result == {"src/foo.py": 1}

    def test_uses_correct_git_command(self, tmp_path):
        from agentpack.core import git
        captured = {}

        def fake_run(args, cwd):
            captured["args"] = args
            captured["cwd"] = cwd
            return ""

        with patch.object(git, "_run", side_effect=fake_run):
            git.file_churn_counts(tmp_path, max_commits=50)

        assert captured["args"] == ["git", "log", "--name-only", "--format=", "-50"]
        assert captured["cwd"] == tmp_path


class TestChurnScoreInScoring:
    def test_high_churn_file_gets_reason(self):
        """A file in the top 10% by churn count gets the 'high churn' reason."""
        w = ScoringWeights(churn_high=15)
        files = [_fi(f"src/module{i}.py") for i in range(20)]
        # Make file 0 very high churn; all others low
        churn_counts = {f"src/module{i}.py": 1 for i in range(20)}
        churn_counts["src/module0.py"] = 100  # clearly in top 10%

        scored = score_files(
            files,
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
            weights=w,
            churn_counts=churn_counts,
        )
        result_map = {fi.path: (score, reasons) for fi, score, reasons in scored}

        score0, reasons0 = result_map["src/module0.py"]
        assert any("high churn" in r for r in reasons0), f"Expected high churn reason, got: {reasons0}"
        assert score0 >= w.churn_high

    def test_low_churn_file_no_reason(self):
        """A file with 0 churn (not in churn_counts) should not get the churn reason."""
        w = ScoringWeights(churn_high=15)
        # 20 files, only half appear in churn_counts (the other half have 0 commits)
        files = [_fi(f"src/module{i}.py") for i in range(20)]
        # Only modules 0-9 appear in churn_counts
        churn_counts = {f"src/module{i}.py": (100 if i == 0 else 5) for i in range(10)}
        # modules 10-19 have no entry (0 churn)

        scored = score_files(
            files,
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
            weights=w,
            churn_counts=churn_counts,
        )
        result_map = {fi.path: (score, reasons) for fi, score, reasons in scored}

        # module15 has 0 churn (not in churn_counts), should NOT get the reason
        _, reasons15 = result_map["src/module15.py"]
        assert not any("high churn" in r for r in reasons15)

    def test_no_churn_counts_no_effect(self):
        """Passing churn_counts=None should not affect scoring."""
        files = [_fi("src/session.py")]
        scored_without = score_files(
            files,
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        scored_with_none = score_files(
            files,
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
            churn_counts=None,
        )
        assert scored_without[0][1] == scored_with_none[0][1]

    def test_churn_weight_configurable(self):
        """Custom churn_high weight is applied."""
        files = [_fi("src/module0.py"), _fi("src/module1.py")]
        churn_counts = {"src/module0.py": 100, "src/module1.py": 1}
        w = ScoringWeights(churn_high=999)
        scored = score_files(
            files,
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
            weights=w,
            churn_counts=churn_counts,
        )
        score_map = {fi.path: score for fi, score, _ in scored}
        # module0 is in top 10%, should get churn_high bonus
        assert score_map["src/module0.py"] >= 999
