from pathlib import Path
from agentpack.analysis.ranking import extract_keywords, extract_keyword_weights, score_files
from agentpack.core.models import FileInfo


def _fi(path: str, tokens: int = 100, language: str = "python") -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path("/nonexistent") / path,
        size_bytes=tokens * 4,
        estimated_tokens=tokens,
        language=language,
    )


def test_extract_keywords_basic():
    kw = extract_keywords("fix Redis SSE cancellation issue")
    assert "redis" in kw
    assert "cancel" in kw  # variant of cancellation
    assert "fix" in kw


def test_extract_keywords_removes_stopwords():
    kw = extract_keywords("the and or but")
    assert len(kw) == 0


def test_extract_keywords_variants():
    kw = extract_keywords("authentication configuration")
    assert "auth" in kw
    assert "config" in kw


def test_extract_keyword_weights_downweight_expanded_concepts():
    weights = extract_keyword_weights("queue")
    assert weights["queue"] == 1.0
    assert weights["task"] < weights["queue"]


def test_changed_file_gets_high_score():
    files = [_fi("src/auth/session.py")]
    scored = score_files(
        files,
        changed_paths={"src/auth/session.py"},
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"auth", "session"},
    )
    assert scored[0][1] >= 100


def test_filename_keyword_match():
    files = [_fi("src/auth/session.py"), _fi("src/billing/invoice.py")]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"auth", "session"},
    )
    scores = {s[0].path: s[1] for s in scored}
    assert scores["src/auth/session.py"] > scores["src/billing/invoice.py"]


def test_filename_keyword_match_uses_whole_tokens():
    files = [_fi("src/tasks.py"), _fi("src/task_runner.py")]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"task"},
    )
    scores = {s[0].path: s[1] for s in scored}
    assert scores["src/tasks.py"] == 0
    assert scores["src/task_runner.py"] > 0


def test_content_keyword_match_uses_whole_tokens():
    fi = _fi("src/status.py")
    fi.content = "def status(): pass\n"
    scored = score_files(
        [fi],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"stat"},
    )
    assert scored[0][1] == 0


def test_concept_keyword_scores_less_than_literal_keyword():
    files = [_fi("src/task.py")]
    literal = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"task": 1.0},
    )
    expanded = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("queue"),
    )
    assert 0 < expanded[0][1] < literal[0][1]


def test_score_includes_reasons():
    files = [_fi("src/redis_client.py")]
    scored = score_files(
        files,
        changed_paths={"src/redis_client.py"},
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords={"redis"},
    )
    reasons = scored[0][2]
    assert any("modified" in r or "keyword" in r for r in reasons)
