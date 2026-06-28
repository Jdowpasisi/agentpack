from agentpack.router.models import RouteResult
from agentpack.router.prompt_builder import build_agent_prompt, render_plain


def test_route_prompt_includes_claim_grounding_contract():
    result = RouteResult(
        task="fix auth token expiry",
        selected_files=[{"path": "src/auth.py", "include_mode": "full"}],
        evidence_checklist=["Inspect token expiry handling."],
    )

    prompt = build_agent_prompt(result)
    plain = render_plain(result)

    assert "Evidence contract:" in prompt
    assert "path:line" in prompt
    assert ".agentpack/citations.json" in prompt
    assert "repo-code claims require `path:line`" in plain
