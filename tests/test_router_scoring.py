from __future__ import annotations

from agentpack.router.models import SkillArtifact
from agentpack.router.scoring import score_skills


def test_scoring_prefers_pytest_and_webhook_skills():
    skills = [
        SkillArtifact(
            name="django-pytest",
            path=".claude/skills/django-pytest/SKILL.md",
            source=".claude/skills",
            description="Use for pytest test debugging, fixtures, mocks, and flaky tests.",
            triggers=["django", "pytest", "test", "fixture", "mock", "flaky"],
            tools_required=["pytest"],
            side_effect_level="command",
            applies_to_paths=["tests/**"],
        ),
        SkillArtifact(
            name="webhook-idempotency",
            path=".agentpack/skills/webhook-idempotency/SKILL.md",
            source=".agentpack/skills",
            description="Use for payment webhook idempotency.",
            triggers=["payment", "webhook", "idempotency"],
            side_effect_level="file_write",
            applies_to_paths=["payments/**"],
        ),
        SkillArtifact(
            name="rca-writer",
            path=".claude/skills/rca-writer/SKILL.md",
            source=".claude/skills",
            description="Use for incident analysis.",
            triggers=["incident", "postmortem", "rca"],
            side_effect_level="none",
        ),
    ]

    selected, warnings, all_scores = score_skills(
        skills,
        task="fix flaky payment webhook test",
        selected_paths=["payments/webhooks.py", "tests/test_payment_webhooks.py"],
        max_selected=3,
        allow_external=False,
    )

    assert warnings == []
    assert [item.skill.name for item in selected[:2]] == ["django-pytest", "webhook-idempotency"]
    assert all_scores[0].score > all_scores[-1].score


def test_external_skill_warned_not_selected_by_default():
    skills = [
        SkillArtifact(
            name="production-deploy-checklist",
            path=".claude/skills/production-deploy-checklist/SKILL.md",
            source=".claude/skills",
            description="Deploy to cloud and migrate production.",
            triggers=["deploy", "cloud", "production"],
            side_effect_level="external",
        )
    ]

    selected, warnings, _all_scores = score_skills(
        skills,
        task="deploy production API",
        selected_paths=["infra/prod-api.conf"],
        max_selected=3,
        allow_external=False,
    )

    assert selected == []
    assert warnings
    assert "production-deploy-checklist" in warnings[0]
