from __future__ import annotations

from agentpack.dashboard.models import (
    BenchmarkSummary,
    ContextHealth,
    DashboardSnapshot,
    LearningArtifact,
    ProjectInfo,
    SelectedFileRow,
    SkillRow,
    SkillSection,
    SuggestedAction,
    TaskInfo,
)
from agentpack.dashboard.renderers import render_dashboard_html


def test_render_dashboard_html_contains_core_sections() -> None:
    html = render_dashboard_html(
        DashboardSnapshot(
            generated_at="2026-06-10T10:30:00Z",
            project=ProjectInfo(name="repo", path="/tmp/repo", branch="main", git_sha="abc123"),
            task=TaskInfo(text="fix auth", state="in_progress"),
            context=ContextHealth(status="fresh", mode="balanced", packed_tokens=1200, raw_tokens=40000),
            selected_files=[SelectedFileRow(path="src/auth.py", include_mode="full", score=120)],
            skills=SkillSection(
                task_specific=[SkillRow(name="auth-review", confidence=0.8, status="used_helpful")]
            ),
            learning=[LearningArtifact(label="Learning notes", path=".agentpack/learning.md", exists=True)],
            benchmarks=BenchmarkSummary(averages={"selection_recall": 0.8}),
            suggested_actions=[SuggestedAction(label="Refresh context", command="agentpack pack --task auto")],
        )
    )

    assert "AgentPack Dashboard" in html
    assert "fix auth" in html
    assert "src/auth.py" in html
    assert "auth-review" in html
    assert "selection_recall" in html
    assert "agentpack pack --task auto" in html


def test_render_dashboard_html_escapes_dynamic_content() -> None:
    html = render_dashboard_html(
        DashboardSnapshot(
            project=ProjectInfo(name="<repo>", path="/tmp/repo"),
            task=TaskInfo(text="<script>alert(1)</script>"),
        )
    )

    assert "&lt;repo&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_render_dashboard_html_uses_no_remote_assets() -> None:
    html = render_dashboard_html(DashboardSnapshot(project=ProjectInfo(name="repo", path="/tmp/repo")))

    assert "https://" not in html
    assert "http://" not in html
    assert "<script" not in html.lower()
