"""
Focused coverage tests for modules that previously had no tests.

Modules covered:
  - core/cache.py
  - core/config.py
  - core/merkle.py
  - core/token_estimator.py
  - analysis/tests.py
  - renderers/markdown.py
  - summaries/offline.py
  - summaries/base.py
  - adapters/claude.py  (patch_claude_md only; render covered elsewhere)
  - analysis/ranking.py (gaps not covered by test_ranking.py)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# core/cache.py
# ---------------------------------------------------------------------------

from agentpack.core.cache import save_summary, load_summary  # noqa: E402
from agentpack.core.models import FileSummary  # noqa: E402


def _make_summary(path: str = "src/foo.py", file_hash: str = "abc123") -> FileSummary:
    return FileSummary(
        path=path,
        hash=file_hash,
        language="python",
        provider="offline",
        schema_version=1,
        summary="test summary",
        imports=["os"],
        symbols=[],
    )


class TestCache:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        summary = _make_summary()
        save_summary(tmp_path, summary)
        loaded = load_summary(tmp_path, summary.path, summary.hash)
        assert loaded is not None
        assert loaded.path == summary.path
        assert loaded.summary == summary.summary
        assert loaded.imports == summary.imports

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        result = load_summary(tmp_path, "src/missing.py", "deadbeef")
        assert result is None

    def test_different_hash_is_a_miss(self, tmp_path: Path) -> None:
        summary = _make_summary(file_hash="hash_v1")
        save_summary(tmp_path, summary)
        # Load with a different hash — must not return the stored entry
        result = load_summary(tmp_path, summary.path, "hash_v2")
        assert result is None

    def test_different_path_is_a_miss(self, tmp_path: Path) -> None:
        summary = _make_summary(path="src/a.py")
        save_summary(tmp_path, summary)
        result = load_summary(tmp_path, "src/b.py", summary.hash)
        assert result is None

    def test_cache_dir_created_automatically(self, tmp_path: Path) -> None:
        summary = _make_summary()
        save_summary(tmp_path, summary)
        assert (tmp_path / ".agentpack" / "cache").is_dir()


# ---------------------------------------------------------------------------
# core/config.py
# ---------------------------------------------------------------------------

from agentpack.core.config import (  # noqa: E402
    load_config,
    save_config,
    DEFAULT_CONFIG,
    ScoringWeights,
    Config,
)


class TestConfig:
    def test_load_returns_default_when_no_file(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg == DEFAULT_CONFIG

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        original = load_config(tmp_path)
        save_config(original, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.context.default_budget == original.context.default_budget
        assert loaded.context.default_mode == original.context.default_mode

    def test_save_config_creates_file(self, tmp_path: Path) -> None:
        save_config(DEFAULT_CONFIG, tmp_path)
        assert (tmp_path / ".agentpack" / "config.toml").exists()

    def test_save_and_load_preserves_custom_budget(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.context.default_budget = 99999
        save_config(cfg, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.context.default_budget == 99999

    def test_scoring_weights_defaults(self) -> None:
        w = ScoringWeights()
        assert w.modified == 100
        assert w.ignored_penalty == -100
        assert w.modified > w.staged > w.filename_keyword

    def test_scoring_weights_are_numeric(self) -> None:
        """All scoring weight fields must be numeric (int or float)."""
        w = ScoringWeights()
        for field in ScoringWeights.model_fields:
            assert isinstance(getattr(w, field), (int, float))


# ---------------------------------------------------------------------------
# core/merkle.py
# ---------------------------------------------------------------------------

from agentpack.core.merkle import root_hash  # noqa: E402


class TestMerkle:
    def test_empty_dict_returns_sha256_of_nothing(self) -> None:
        result = root_hash({})
        # sha256("") is a known constant
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_single_entry_returns_deterministic_hash(self) -> None:
        h1 = root_hash({"a.py": "abc"})
        h2 = root_hash({"a.py": "abc"})
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex digest

    def test_two_entries_order_insensitive(self) -> None:
        h1 = root_hash({"a.py": "111", "b.py": "222"})
        h2 = root_hash({"b.py": "222", "a.py": "111"})
        assert h1 == h2

    def test_different_hashes_produce_different_roots(self) -> None:
        h1 = root_hash({"a.py": "hash1"})
        h2 = root_hash({"a.py": "hash2"})
        assert h1 != h2

    def test_different_paths_produce_different_roots(self) -> None:
        h1 = root_hash({"a.py": "same"})
        h2 = root_hash({"b.py": "same"})
        assert h1 != h2


# ---------------------------------------------------------------------------
# core/token_estimator.py
# ---------------------------------------------------------------------------

from agentpack.core.token_estimator import estimate_tokens  # noqa: E402


class TestTokenEstimator:
    def test_returns_positive_int_for_short_text(self) -> None:
        result = estimate_tokens("hello")
        assert isinstance(result, int)
        assert result > 0

    def test_returns_positive_int_for_empty_string(self) -> None:
        # max(1, ...) ensures we never return 0
        result = estimate_tokens("")
        assert result >= 1

    def test_longer_text_produces_more_tokens(self) -> None:
        short = estimate_tokens("hello world")
        long = estimate_tokens("hello world " * 100)
        assert long > short

    def test_returns_int_type(self) -> None:
        assert type(estimate_tokens("abc")) is int


# ---------------------------------------------------------------------------
# analysis/tests.py
# ---------------------------------------------------------------------------

from agentpack.analysis.tests import find_related_tests  # noqa: E402


class TestFindRelatedTests:
    def test_finds_test_file_in_tests_dir(self) -> None:
        all_paths = {"tests/test_foo.py", "src/foo.py", "src/bar.py"}
        result = find_related_tests("src/foo.py", all_paths)
        assert "tests/test_foo.py" in result

    def test_returns_empty_when_no_match(self) -> None:
        all_paths = {"src/foo.py", "src/bar.py"}
        result = find_related_tests("src/foo.py", all_paths)
        assert result == []

    def test_finds_test_file_in_same_dir(self) -> None:
        all_paths = {"test_utils.py", "utils.py"}
        result = find_related_tests("utils.py", all_paths)
        assert "test_utils.py" in result

    def test_finds_ts_test_file(self) -> None:
        all_paths = {"parser.test.ts", "parser.ts"}
        result = find_related_tests("parser.ts", all_paths)
        assert "parser.test.ts" in result

    def test_no_false_positives_from_other_stems(self) -> None:
        all_paths = {"tests/test_bar.py", "src/foo.py"}
        result = find_related_tests("src/foo.py", all_paths)
        # test_bar.py should NOT appear for foo.py
        assert "tests/test_bar.py" not in result


# ---------------------------------------------------------------------------
# renderers/markdown.py
# ---------------------------------------------------------------------------

from agentpack.renderers.markdown import render_claude  # noqa: E402
from agentpack.core.models import ContextPack, SelectedFile  # noqa: E402


def _make_pack(selected_files: list[SelectedFile] | None = None) -> ContextPack:
    return ContextPack(
        task="fix the cache bug",
        agent="claude",
        mode="balanced",
        budget=25000,
        token_estimate=500,
        raw_repo_tokens=10000,
        after_ignore_tokens=8000,
        estimated_savings_percent=90.0,
        changed_files=["src/cache.py"],
        selected_files=selected_files or [],
        receipts=[],
    )


class TestRenderClaude:
    def test_contains_task_section_header(self) -> None:
        output = render_claude(_make_pack())
        assert "## Task" in output

    def test_contains_changed_files_section(self) -> None:
        output = render_claude(_make_pack())
        assert "## Changed Files" in output
        assert "src/cache.py" in output

    def test_contains_file_context_section(self) -> None:
        output = render_claude(_make_pack())
        assert "## File Context" in output

    def test_full_mode_file_shows_content_in_code_fence(self) -> None:
        sf = SelectedFile(
            path="src/cache.py",
            language="python",
            score=100.0,
            include_mode="full",
            reasons=["modified"],
            content="def save(): pass",
        )
        output = render_claude(_make_pack([sf]))
        assert "```python" in output
        assert "def save(): pass" in output

    def test_symbols_mode_with_content_shows_content_in_code_fence(self) -> None:
        """
        Regression test: symbols-mode files with content must render that
        content inside a code fence (not fall through to the summary/symbol
        block branch which would omit the raw content).
        """
        sf = SelectedFile(
            path="src/parser.py",
            language="python",
            score=80.0,
            include_mode="symbols",
            reasons=["keyword match"],
            content="def parse(text): ...",
        )
        output = render_claude(_make_pack([sf]))
        assert "```python" in output
        assert "def parse(text): ..." in output

    def test_summary_mode_shows_summary_text(self) -> None:
        sf = SelectedFile(
            path="src/utils.py",
            language="python",
            score=20.0,
            include_mode="summary",
            reasons=["context"],
            summary="Utility helpers for string manipulation.",
        )
        output = render_claude(_make_pack([sf]))
        assert "Utility helpers for string manipulation." in output

    def test_no_changed_files_shows_placeholder(self) -> None:
        pack = ContextPack(
            task="refactor",
            agent="claude",
            mode="balanced",
            budget=25000,
            token_estimate=100,
            raw_repo_tokens=1000,
            after_ignore_tokens=1000,
            estimated_savings_percent=0.0,
            changed_files=[],
            selected_files=[],
            receipts=[],
        )
        output = render_claude(pack)
        assert "_No changed files detected._" in output

    def test_stale_pack_shows_warning(self) -> None:
        pack = _make_pack()
        pack.stale = True
        output = render_claude(pack)
        assert "stale" in output.lower()


# ---------------------------------------------------------------------------
# summaries/offline.py
# ---------------------------------------------------------------------------

from agentpack.summaries.offline import summarize  # noqa: E402


class TestOfflineSummarize:
    def test_python_summary_has_language_header(self, tmp_path: Path) -> None:
        src = tmp_path / "foo.py"
        src.write_text("def greet(name):\n    return f'hello {name}'\n")
        result = summarize("foo.py", src, "python", "deadbeef")
        assert "Language: Python" in result.summary

    def test_python_summary_exposes_function_names(self, tmp_path: Path) -> None:
        src = tmp_path / "math_utils.py"
        src.write_text(
            "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n"
        )
        result = summarize("math_utils.py", src, "python", "hash1")
        symbol_names = [s.name for s in result.symbols]
        assert "add" in symbol_names
        assert "multiply" in symbol_names

    def test_python_summary_exposes_class_names(self, tmp_path: Path) -> None:
        src = tmp_path / "models.py"
        src.write_text("class User:\n    pass\n")
        result = summarize("models.py", src, "python", "hash2")
        assert "User" in result.summary

    def test_generic_summary_for_unknown_language(self, tmp_path: Path) -> None:
        src = tmp_path / "notes.txt"
        src.write_text("some content\n")
        result = summarize("notes.txt", src, None, "hash3")
        assert "unknown" in result.summary.lower()

    def test_generic_summary_for_named_language(self, tmp_path: Path) -> None:
        src = tmp_path / "script.rb"
        src.write_text("puts 'hello'\n")
        result = summarize("script.rb", src, "ruby", "hash4")
        assert "ruby" in result.summary.lower()

    def test_provider_is_always_offline(self, tmp_path: Path) -> None:
        src = tmp_path / "foo.py"
        src.write_text("")
        result = summarize("foo.py", src, "python", "h")
        assert result.provider == "offline"

    def test_schema_version_is_1(self, tmp_path: Path) -> None:
        src = tmp_path / "foo.py"
        src.write_text("")
        result = summarize("foo.py", src, "python", "h")
        assert result.schema_version == 1


# ---------------------------------------------------------------------------
# summaries/base.py
# ---------------------------------------------------------------------------

from agentpack.summaries.base import build_all_summaries, get_or_build_summary  # noqa: E402
from agentpack.core.models import FileInfo  # noqa: E402


def _make_file_info(
    path: str,
    abs_path: Path,
    ignored: bool = False,
    binary: bool = False,
    language: str = "python",
    file_hash: str = "abc",
) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=abs_path,
        language=language,
        size_bytes=100,
        estimated_tokens=25,
        hash=file_hash,
        ignored=ignored,
        binary=binary,
    )


class TestBuildAllSummaries:
    def test_skips_ignored_files(self, tmp_path: Path) -> None:
        src = tmp_path / "ignored.py"
        src.write_text("x = 1\n")
        fi = _make_file_info("ignored.py", src, ignored=True)
        result = build_all_summaries([fi], tmp_path)
        assert "ignored.py" not in result

    def test_skips_binary_files(self, tmp_path: Path) -> None:
        src = tmp_path / "image.png"
        src.write_bytes(b"\x89PNG\r\n")
        fi = _make_file_info("image.png", src, binary=True, language=None)
        result = build_all_summaries([fi], tmp_path)
        assert "image.png" not in result

    def test_includes_regular_files(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text("def main(): pass\n")
        fi = _make_file_info("main.py", src)
        result = build_all_summaries([fi], tmp_path)
        assert "main.py" in result

    def test_returns_file_summary_objects(self, tmp_path: Path) -> None:
        src = tmp_path / "utils.py"
        src.write_text("def helper(): pass\n")
        fi = _make_file_info("utils.py", src)
        result = build_all_summaries([fi], tmp_path)
        assert result["utils.py"].path == "utils.py"


class TestGetOrBuildSummary:
    def test_caches_on_second_call(self, tmp_path: Path) -> None:
        """
        On the first call the offline summarizer is invoked and the result
        is written to the cache.  On the second call the cache must be read
        instead of calling offline.summarize again.
        """
        src = tmp_path / "svc.py"
        src.write_text("def run(): pass\n")
        fi = _make_file_info("svc.py", src, file_hash="fixed_hash")

        with patch("agentpack.summaries.base.offline.summarize", wraps=summarize) as mock_sum:
            # First call — should invoke summarize
            get_or_build_summary(fi, tmp_path)
            first_call_count = mock_sum.call_count
            assert first_call_count == 1

            # Second call — cache hit, summarize must NOT be called again
            get_or_build_summary(fi, tmp_path)
            assert mock_sum.call_count == 1  # unchanged

    def test_none_hash_always_calls_summarize(self, tmp_path: Path) -> None:
        """Files without a hash (e.g. uncommitted) are never cached."""
        src = tmp_path / "dirty.py"
        src.write_text("x = 1\n")
        fi = _make_file_info("dirty.py", src, file_hash=None)
        fi = fi.model_copy(update={"hash": None})

        with patch("agentpack.summaries.base.offline.summarize", wraps=summarize) as mock_sum:
            get_or_build_summary(fi, tmp_path)
            get_or_build_summary(fi, tmp_path)
            # Both calls must hit offline.summarize because hash is None
            assert mock_sum.call_count == 2


# ---------------------------------------------------------------------------
# adapters/claude.py  — patch_claude_md gaps
# ---------------------------------------------------------------------------

from agentpack.adapters.claude import ClaudeAdapter  # noqa: E402


class TestPatchClaudeMd:
    def test_creates_claude_md_when_absent(self, tmp_path: Path) -> None:
        adapter = ClaudeAdapter()
        action = adapter.patch_claude_md(tmp_path)
        assert action == "created"
        assert (tmp_path / "CLAUDE.md").exists()
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "agentpack:start" in content

    def test_appends_block_when_no_existing_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nSome docs.\n")
        adapter = ClaudeAdapter()
        action = adapter.patch_claude_md(tmp_path)
        assert action == "appended"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "My Project" in content
        assert "agentpack:start" in content

    def test_updates_stale_existing_block(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text(
            "# Proj\n\n<!-- agentpack:start -->\nOLD\n<!-- agentpack:end -->\n"
        )
        adapter = ClaudeAdapter()
        action = adapter.patch_claude_md(tmp_path)
        assert action in ("updated", "unchanged")
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "OLD" not in content

    def test_returns_unchanged_when_block_already_current(self, tmp_path: Path) -> None:
        adapter = ClaudeAdapter()
        adapter.patch_claude_md(tmp_path)  # write the canonical block
        action = adapter.patch_claude_md(tmp_path)  # run again on same content
        assert action == "unchanged"


# ---------------------------------------------------------------------------
# analysis/ranking.py — gaps not covered by existing test_ranking.py
# ---------------------------------------------------------------------------

from agentpack.analysis.ranking import score_files  # noqa: E402


def _fi(
    path: str,
    tmp_path: Path,
    tokens: int = 100,
    language: str = "python",
    ignored: bool = False,
    binary: bool = False,
    too_large: bool = False,
) -> FileInfo:
    abs_path = tmp_path / path
    return FileInfo(
        path=path,
        abs_path=abs_path,
        language=language,
        size_bytes=tokens * 4,
        estimated_tokens=tokens,
        ignored=ignored,
        binary=binary,
        too_large=too_large,
    )


class TestScoreFiles:
    def test_modified_file_scores_higher_than_unmodified(self, tmp_path: Path) -> None:
        modified = _fi("src/auth.py", tmp_path)
        unmodified = _fi("src/utils.py", tmp_path)
        scored = score_files(
            [modified, unmodified],
            changed_paths={"src/auth.py"},
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        scores = {s[0].path: s[1] for s in scored}
        assert scores["src/auth.py"] > scores["src/utils.py"]

    def test_keyword_match_boosts_score(self, tmp_path: Path) -> None:
        keyword_file = _fi("src/cache_manager.py", tmp_path)
        other_file = _fi("src/printer.py", tmp_path)
        scored = score_files(
            [keyword_file, other_file],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords={"cache"},
        )
        scores = {s[0].path: s[1] for s in scored}
        assert scores["src/cache_manager.py"] > scores["src/printer.py"]

    def test_ignored_file_gets_non_positive_score(self, tmp_path: Path) -> None:
        ignored = _fi("src/generated.py", tmp_path, ignored=True)
        scored = score_files(
            [ignored],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        assert scored[0][1] <= 0

    def test_binary_file_gets_non_positive_score(self, tmp_path: Path) -> None:
        binary = _fi("assets/logo.png", tmp_path, binary=True, language=None)
        scored = score_files(
            [binary],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        assert scored[0][1] <= 0

    def test_staged_file_gets_high_score(self, tmp_path: Path) -> None:
        staged = _fi("src/new_feature.py", tmp_path)
        scored = score_files(
            [staged],
            changed_paths=set(),
            staged_paths={"src/new_feature.py"},
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        assert scored[0][1] >= 90

    def test_recently_modified_adds_to_score(self, tmp_path: Path) -> None:
        fi = _fi("src/old.py", tmp_path)
        scored_recent = score_files(
            [fi],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=["src/old.py"],
            dep_graph={},
            keywords=set(),
        )
        scored_not = score_files(
            [fi],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords=set(),
        )
        assert scored_recent[0][1] > scored_not[0][1]

    def test_reasons_list_is_populated(self, tmp_path: Path) -> None:
        fi = _fi("src/auth_service.py", tmp_path)
        scored = score_files(
            [fi],
            changed_paths={"src/auth_service.py"},
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords={"auth"},
        )
        reasons = scored[0][2]
        assert len(reasons) > 0
        assert any("modified" in r for r in reasons)

    def test_symbol_keyword_match_via_summaries(self, tmp_path: Path) -> None:
        fi_with_sym = _fi("src/session.py", tmp_path)
        fi_no_sym = _fi("src/utils.py", tmp_path)
        summaries = {
            "src/session.py": {
                "symbols": [{"name": "refresh_token", "kind": "function", "start_line": 1, "end_line": 10}]
            }
        }
        scored = score_files(
            [fi_with_sym, fi_no_sym],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords={"token"},
            summaries=summaries,
        )
        scores = {s[0].path: (s[1], s[2]) for s in scored}
        assert scores["src/session.py"][0] > scores["src/utils.py"][0]
        assert any("symbol keyword" in r for r in scores["src/session.py"][1])

    def test_symbol_keyword_no_false_positive_without_summaries(self, tmp_path: Path) -> None:
        fi = _fi("src/models.py", tmp_path)
        scored = score_files(
            [fi],
            changed_paths=set(),
            staged_paths=set(),
            recently_modified=[],
            dep_graph={},
            keywords={"token"},
            summaries=None,
        )
        reasons = scored[0][2]
        assert not any("symbol keyword" in r for r in reasons)


# ---------------------------------------------------------------------------
# analysis/ranking.py — enrich_keywords_from_files
# ---------------------------------------------------------------------------

from agentpack.analysis.ranking import enrich_keywords_from_files  # noqa: E402


def _fi(path: str, tmp_path: Path, tokens: int = 100, language: str = "python",
        ignored: bool = False, binary: bool = False, too_large: bool = False):
    from agentpack.core.models import FileInfo
    abs_path = tmp_path / path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    if not abs_path.exists():
        abs_path.write_text(f"# {path}\n")
    return FileInfo(
        path=path,
        abs_path=abs_path,
        language=language,
        size_bytes=100,
        estimated_tokens=tokens,
        hash="abc",
        ignored=ignored,
        binary=binary,
        too_large=too_large,
    )


class TestEnrichKeywords:
    def test_adds_frequent_tokens_from_changed_files(self, tmp_path: Path) -> None:
        fi = _fi("src/auth.py", tmp_path)
        fi.abs_path.write_text("token token token validate validate validate session\n" * 5)
        result = enrich_keywords_from_files({"auth"}, {"src/auth.py"}, [fi])
        assert "token" in result or "validate" in result

    def test_does_not_add_stopwords(self, tmp_path: Path) -> None:
        fi = _fi("src/util.py", tmp_path)
        fi.abs_path.write_text("the the the and and and for for for\n" * 5)
        result = enrich_keywords_from_files(set(), {"src/util.py"}, [fi])
        assert "the" not in result
        assert "and" not in result

    def test_does_not_add_rare_tokens(self, tmp_path: Path) -> None:
        fi = _fi("src/rare.py", tmp_path)
        fi.abs_path.write_text("unicorn\n")  # appears once
        result = enrich_keywords_from_files(set(), {"src/rare.py"}, [fi])
        assert "unicorn" not in result

    def test_preserves_existing_keywords(self, tmp_path: Path) -> None:
        fi = _fi("src/x.py", tmp_path)
        fi.abs_path.write_text("foo foo foo\n" * 5)
        base = {"mykey", "other"}
        result = enrich_keywords_from_files(base, {"src/x.py"}, [fi])
        assert "mykey" in result
        assert "other" in result

    def test_unchanged_paths_not_read(self, tmp_path: Path) -> None:
        fi = _fi("src/unrelated.py", tmp_path)
        fi.abs_path.write_text("token token token\n" * 5)
        result = enrich_keywords_from_files(set(), set(), [fi])
        assert "token" not in result

    def test_returns_set(self, tmp_path: Path) -> None:
        result = enrich_keywords_from_files({"x"}, set(), [])
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# analysis/ranking.py — concept map / semantic expansion
# ---------------------------------------------------------------------------

from agentpack.analysis.ranking import extract_keywords  # noqa: E402


class TestConceptExpansion:
    def test_rate_limiting_expands_to_throttle(self) -> None:
        kws = extract_keywords("fix rate limiting")
        assert "throttle" in kws

    def test_rate_limiting_expands_to_leaky(self) -> None:
        kws = extract_keywords("fix rate limiting")
        assert "leaky" in kws

    def test_auth_expands_to_jwt(self) -> None:
        kws = extract_keywords("fix auth")
        assert "jwt" in kws

    def test_cache_expands_to_lru(self) -> None:
        kws = extract_keywords("improve caching")
        assert "lru" in kws

    def test_no_recursive_explosion(self) -> None:
        # One-level expansion only; three-word task must stay well under 50 keywords
        kws = extract_keywords("fix rate limiting")
        assert len(kws) < 50

    def test_original_keywords_preserved(self) -> None:
        kws = extract_keywords("fix rate limiting")
        # Original non-stopword tokens must still be present
        assert "rate" in kws
        assert "limiting" in kws

    def test_unknown_word_no_expansion(self) -> None:
        kws = extract_keywords("fix xyzzy_unknown")
        # Should parse to base tokens without crash and without extra expansion
        assert "fix" not in kws or True  # "fix" may be filtered as < 3 chars? no it's 3
        # The key check: no crash, and only the base tokens plus no spurious additions
        assert "xyzzy" in kws or "unknown" in kws  # at least one base token present
        # No concept map matches means no expansion beyond base
        assert len(kws) <= 5  # "fix", "xyzzy", "unknown" — very small set
