from pathlib import Path
from agentpack.analysis.ranking import (
    ambiguous_task_terms,
    build_keyword_plan,
    boost_cross_layer_related,
    concrete_task_terms,
    extract_keywords,
    extract_keyword_weights,
    generic_task_term_ratio,
    persist_keyword_plan_stats,
    score_files,
    suggest_task_rewrite,
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


def test_ambiguous_task_terms_are_softened_but_preserved():
    weights = extract_keyword_weights("public analysis seo preview")
    assert weights["analysis"] < weights["seo"]
    assert weights["public"] < weights["seo"]
    assert ambiguous_task_terms("public analysis seo preview") == ["analysis", "preview", "public"]
    assert concrete_task_terms("public analysis seo preview") == ["seo"]


def test_task_rewrite_hint_prefers_scope_and_concrete_terms():
    hint = suggest_task_rewrite("Implement cost-safe public SEO tools with deterministic previews and signup-gated AI analysis")
    assert "frontend page/component work only" in hint
    assert "seo" in hint
    assert "no backend service or analysis changes" in hint


def test_keyword_plan_uses_repo_rarity_to_lift_concrete_terms():
    files = [
        _fi("src/common/preview_card.py"),
        _fi("src/common/preview_modal.py"),
        _fi("src/common/preview_shell.py"),
        _fi("src/seo/landing_tool.py"),
    ]
    plan = build_keyword_plan("preview seo", files=files)
    assert plan.weights["seo"] > plan.weights["preview"]
    assert plan.rarity["seo"] > plan.rarity["preview"]


def test_keyword_plan_learns_ambiguous_terms_from_noisy_history(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join([
            '{"task":"public preview analysis flow","selection_token_precision":0.1,"selection_noise_paths":["src/noisy.py"]}',
            '{"task":"public preview analysis page","selection_token_precision":0.12,"selection_noise_paths":["src/noisy.py"]}',
            '{"task":"seo landing page","selection_token_precision":0.6,"selection_noise_paths":[]}',
        ]),
        encoding="utf-8",
    )
    plan = build_keyword_plan("public preview analysis seo", root=tmp_path)
    assert "preview" in plan.learned_ambiguous_terms
    assert plan.weights["preview"] <= 0.55


def test_keyword_plan_learns_positive_terms_and_phrases(tmp_path):
    metrics_dir = tmp_path / ".agentpack"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.jsonl").write_text(
        "\n".join([
            '{"task":"signup gate preview","selection_token_precision":0.62,"selection_noise_paths":[]}',
            '{"task":"signup gate flow","selection_token_precision":0.58,"selection_noise_paths":[]}',
            '{"task":"preview analysis page","selection_token_precision":0.1,"selection_noise_paths":["src/noisy.py"]}',
        ]),
        encoding="utf-8",
    )
    plan = build_keyword_plan("signup gate preview", root=tmp_path)
    assert "signup" in plan.learned_positive_terms
    assert "signup gate" in plan.learned_positive_phrases
    assert plan.phrase_weights["signup gate"] > plan.phrase_weights["gate preview"]


def test_keyword_plan_workspace_weights_can_exceed_global_for_local_rarity():
    files = [
        _fi("apps/web/src/signup_gate.tsx"),
        _fi("apps/web/src/preview_card.tsx"),
        _fi("apps/api/src/signup_worker.ts"),
        _fi("apps/api/src/preview_job.ts"),
    ]
    plan = build_keyword_plan(
        "signup preview",
        files=files,
        workspace_roots=["apps/web", "apps/api"],
    )
    assert plan.workspace_weights["apps/web"]["signup"] >= plan.weights["signup"]


def test_keyword_plan_persists_term_stats(tmp_path):
    plan = build_keyword_plan("signup gate preview")
    out = persist_keyword_plan_stats(tmp_path, "signup gate preview", plan)
    text = out.read_text(encoding="utf-8")
    assert '"task": "signup gate preview"' in text
    assert '"terms"' in text
    assert '"phrases"' in text


def test_ambiguous_terms_restore_only_with_corroboration():
    weak = _fi("src/analysis.py")
    weak.content = "def helper():\n    return 1\n"
    strong = _fi("src/services/analysis_service.py")
    strong.content = "def analysis():\n    return analysis_result\nanalysis_result = analysis()\n"
    strong.language = "python"

    plan = build_keyword_plan("analysis", files=[weak, strong])
    scored = score_files(
        [weak, strong],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=plan,
    )
    reasons = {fi.path: rs for fi, _score, rs in scored}
    assert any(reason.startswith("ambiguous term cap") for reason in reasons["src/analysis.py"])
    assert any(reason.startswith("ambiguous term restored by corroboration") for reason in reasons["src/services/analysis_service.py"])


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
