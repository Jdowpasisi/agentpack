from agentpack.analysis.context_intent import broad_context_enabled, infer_context_intent


def test_infer_context_intent_for_broad_workflows() -> None:
    assert infer_context_intent("share broad repo context for review") == "review"
    assert infer_context_intent("prepare repository overview for handoff") == "share"
    assert infer_context_intent("audit auth flow for security") == "audit"
    assert infer_context_intent("fix auth token expiry") == "coding_task"


def test_broad_context_enabled_respects_config() -> None:
    assert broad_context_enabled("auto", "review") is True
    assert broad_context_enabled("auto", "coding_task") is False
    assert broad_context_enabled("on", "coding_task") is True
    assert broad_context_enabled("off", "review") is False
