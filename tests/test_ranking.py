from pathlib import Path
from agentpack.analysis.ranking import (
    boost_cross_layer_related,
    extract_keywords,
    extract_keyword_weights,
    generic_task_term_ratio,
    score_files,
)
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


def test_generic_task_terms_are_downweighted():
    weights = extract_keyword_weights("fix auth implementation")
    assert weights["fix"] < weights["auth"]
    assert weights["impl"] < weights["auth"]
    assert generic_task_term_ratio("fix release implementation task") >= 0.75
    assert generic_task_term_ratio("improve context pack quality from stats") >= 0.8


def test_generic_terms_do_not_dominate_concrete_file_matches():
    files = [_fi("src/release_notes.py"), _fi("src/auth/session.py")]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix auth release implementation"),
    )
    scores = {s[0].path: s[1] for s in scored}
    assert scores["src/auth/session.py"] > scores["src/release_notes.py"]


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


def test_kundali_expands_to_astrology_domain_terms():
    kw = extract_keywords("fix Kundali chart compatibility flow")
    assert "kundali" in kw
    assert "astrology" in kw
    assert "horoscope" in kw or "chart" in kw


def test_implementation_role_boost_keeps_astrology_service_above_summary_floor():
    files = [
        _fi("frontend/app/charts/page.tsx", language="typescript"),
        _fi("backend/src/services/astrology.service.ts", language="typescript"),
        _fi("backend/src/handlers/astrology_handler.py"),
        _fi("backend/src/utils/date_format.py"),
    ]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix Kundali chart compatibility flow"),
    )
    scores = {s[0].path: s[1] for s in scored}
    reasons = {s[0].path: s[2] for s in scored}

    assert scores["backend/src/services/astrology.service.ts"] >= 60
    assert scores["backend/src/handlers/astrology_handler.py"] >= 60
    assert scores["backend/src/services/astrology.service.ts"] > scores["backend/src/utils/date_format.py"]
    assert "implementation role match" in reasons["backend/src/services/astrology.service.ts"]


def test_cross_layer_boost_connects_page_to_matching_service():
    files = [
        _fi("frontend/app/charts/page.tsx", language="typescript"),
        _fi("backend/src/services/chart.service.ts", language="typescript"),
        _fi("backend/src/services/payment.service.ts", language="typescript"),
    ]
    scored = score_files(
        files,
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix chart rendering"),
    )
    boosted = boost_cross_layer_related(scored, extract_keyword_weights("fix chart rendering"))
    scores = {s[0].path: s[1] for s in boosted}
    reasons = {s[0].path: s[2] for s in boosted}

    assert scores["backend/src/services/chart.service.ts"] > scores["backend/src/services/payment.service.ts"]
    assert "cross-layer related implementation" in reasons["backend/src/services/chart.service.ts"]


def test_strong_public_name_gets_bonus():
    fi = _fi("src/auth/otp.py")
    summaries = {
        fi.path: {
            "symbols": [],
            "naming_signals": ["strong public name: verify_otp"],
            "naming_keywords": ["verify", "otp"],
        }
    }
    scored = score_files(
        [fi],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix otp verify issue"),
        summaries=summaries,
    )
    assert any("matched naming keyword:" in reason for reason in scored[0][2])


def test_generic_public_name_gets_small_penalty_when_otherwise_weak():
    good = _fi("src/auth/otp.py")
    weak = _fi("src/auth/handler.py")
    summaries = {
        good.path: {
            "symbols": [],
            "naming_signals": ["strong public name: verify_otp"],
            "naming_keywords": ["verify", "otp"],
        },
        weak.path: {
            "symbols": [],
            "naming_signals": ["generic public name: handle"],
            "naming_keywords": [],
        },
    }
    scored = score_files(
        [good, weak],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix otp verify issue"),
        summaries=summaries,
    )
    scores = {item[0].path: item[1] for item in scored}
    reasons = {item[0].path: item[2] for item in scored}
    assert scores["src/auth/otp.py"] > scores["src/auth/handler.py"]
    assert any(reason == "generic public API penalty: handle" for reason in reasons["src/auth/handler.py"])
