from __future__ import annotations

from agentpack.dashboard.models import (
    ContextHealth,
    DashboardSnapshot,
    ProjectInfo,
    SelectedFileRow,
    SkillRow,
    SkillSection,
    TaskInfo,
)


def test_dashboard_snapshot_is_json_safe() -> None:
    snapshot = DashboardSnapshot(
        generated_at="2026-06-10T10:30:00Z",
        project=ProjectInfo(name="repo", path="/tmp/repo", branch="main", git_sha="abc123"),
        task=TaskInfo(text="fix auth", state="in_progress"),
        context=ContextHealth(status="fresh", mode="balanced", packed_tokens=1200, raw_tokens=40000),
        selected_files=[
            SelectedFileRow(
                path="src/auth.py",
                include_mode="full",
                score=120.0,
                tokens=450,
                reasons=["task keyword match"],
            )
        ],
        skills=SkillSection(
            task_specific=[
                SkillRow(
                    name="pytest-debugging",
                    path="skills/pytest-debugging/SKILL.md",
                    confidence=0.86,
                    score=93.0,
                    side_effect_level="command",
                    status="used_helpful",
                    reasons=["test task match"],
                )
            ]
        ),
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["schema_version"] == 1
    assert payload["project"]["name"] == "repo"
    assert payload["selected_files"][0]["path"] == "src/auth.py"
    assert payload["skills"]["task_specific"][0]["status"] == "used_helpful"
