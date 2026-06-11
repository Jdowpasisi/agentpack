from __future__ import annotations

import json

from agentpack.core.config import LoopConfig
from agentpack.core.loop_protocol import LoopCommandResult, initialize_loop, save_loop_state
from agentpack.dashboard.collectors import build_project_dashboard_snapshot
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


def test_project_dashboard_missing_agentpack_has_empty_states(tmp_path) -> None:
    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.project.name == tmp_path.name
    assert snapshot.context.status == "missing"
    assert any(action.command == "agentpack init --yes" for action in snapshot.suggested_actions)


def test_project_dashboard_reads_pack_metadata_and_metrics(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "task.md").write_text("fix auth token expiry\n", encoding="utf-8")
    (agentpack / "pack_metadata.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-10T10:30:00Z",
                "task": "fix auth token expiry",
                "mode": "balanced",
                "token_estimate": 1450,
                "raw_tokens": 40000,
                "saving_pct": 96.3,
                "selected_files_meta": [
                    {
                        "path": "src/auth/token.py",
                        "mode": "full",
                        "score": 120,
                        "tokens": 450,
                        "reasons": ["task keyword match", "related test"],
                    }
                ],
                "freshness": {"status": "fresh"},
            }
        ),
        encoding="utf-8",
    )
    (agentpack / "metrics.jsonl").write_text(
        json.dumps({"selection_recall": 0.8, "selection_token_precision": 0.5}) + "\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.task.text == "fix auth token expiry"
    assert snapshot.context.status == "fresh"
    assert snapshot.context.packed_tokens == 1450
    assert snapshot.context.raw_tokens == 40000
    assert snapshot.selected_files[0].path == "src/auth/token.py"
    assert snapshot.benchmarks.averages["selection_recall"] == 0.8


def test_project_dashboard_summarizes_skill_feedback(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "skill_feedback.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"recommended_skills": ["auth-review"], "task": "fix auth"}),
                json.dumps({"used_skills": ["auth-review"], "tests_passed": True, "user_feedback": "helpful"}),
                json.dumps({"ignored_skills": ["deploy-checklist"], "user_feedback": "ignored"}),
                json.dumps({"bad_recommendations": ["deploy-checklist"], "user_feedback": "noisy"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (agentpack / "pack_metadata.json").write_text(
        json.dumps(
            {
                "selected_skills": [
                    {
                        "skill": {
                            "name": "auth-review",
                            "path": "skills/auth-review/SKILL.md",
                            "side_effect_level": "none",
                        },
                        "confidence": 0.8,
                        "score": 80,
                        "reasons": ["task keyword match"],
                    },
                    {
                        "skill": {
                            "name": "deploy-checklist",
                            "path": "skills/deploy/SKILL.md",
                            "side_effect_level": "external",
                        },
                        "confidence": 0.7,
                        "score": 70,
                        "reasons": ["task keyword match"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    statuses = {skill.name: skill.status for skill in snapshot.skills.task_specific}
    assert statuses["auth-review"] == "used_helpful"
    assert statuses["deploy-checklist"] == "bad_recommendation"


def test_project_dashboard_caps_jsonl_rows(tmp_path) -> None:
    agentpack = tmp_path / ".agentpack"
    agentpack.mkdir()
    (agentpack / "metrics.jsonl").write_text(
        "".join(json.dumps({"selection_recall": idx / 1000}) + "\n" for idx in range(700)),
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert 0.0 < snapshot.benchmarks.averages["selection_recall"] <= 1.0


def test_project_dashboard_collects_loop_state(tmp_path) -> None:
    state = initialize_loop(tmp_path, "fix auth", LoopConfig(runner="agent", verification_commands=["pytest -q"]))
    state.status = "ready_to_finish"
    state.last_verification = LoopCommandResult(command="pytest -q", returncode=0, output_excerpt="passed")
    save_loop_state(tmp_path, state)

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.loop.exists is True
    assert snapshot.loop.status == "ready_to_finish"
    assert snapshot.loop.last_verification_status == "passed"
    assert snapshot.loop.next_action == "agentpack finish --since main"


def test_project_dashboard_collects_skills_inventory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    skill = tmp_path / ".agentpack" / "skills" / "pytest-debugging" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: pytest-debugging\n"
        "domains: [quality]\n"
        "task_types: [testing]\n"
        "languages: [python]\n"
        "frameworks: [pytest]\n"
        "---\n\n"
        "Use for pytest failures.\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    assert snapshot.skills_inventory.total_skills == 1
    assert snapshot.skills_inventory.total_rules == 0
    assert snapshot.skills_inventory.domains[0].name == "quality"
    assert snapshot.skills_inventory.rows[0].name == "pytest-debugging"
    assert snapshot.skills_inventory.rows[0].domains == ["quality"]
    assert snapshot.skills_inventory.rows[0].metadata_quality == "explicit"
    assert snapshot.skills_inventory.rows[0].domain_confidence == 1.0
    assert snapshot.skills_inventory.rows[0].domain_source == "explicit domains"
    assert snapshot.skills_inventory.index_refreshed is True


def test_project_dashboard_infers_skill_inventory_domains_with_bm25(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    skill = tmp_path / ".agentpack" / "skills" / "academic-cv-builder" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "# Academic CV Builder\n\n"
        "Use this when creating academic CVs, resumes, cover letters, and job application portfolios.\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    row = snapshot.skills_inventory.rows[0]
    assert row.name == "Academic CV Builder"
    assert row.domains == ["career"]
    assert row.metadata_quality == "inferred"
    assert "domain source: bm25" in row.metadata
    assert "inferred domains: career" in row.metadata
    assert 0.0 < row.domain_confidence < 1.0
    assert any(item.startswith("description:") for item in row.metadata)
    assert snapshot.skills_inventory.uncategorized_count == 0


def test_project_dashboard_filters_generic_inferred_skill_triggers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    skill = tmp_path / ".agentpack" / "skills" / "graphql-architect" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: graphql-architect\n"
        "description: Use when designing GraphQL schemas, implementing Apollo Federation, or building real-time subscriptions with DataLoader.\n"
        "---\n\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    metadata = snapshot.skills_inventory.rows[0].metadata
    trigger_line = next(item for item in metadata if item.startswith("triggers:"))
    assert "graphql-architect" not in trigger_line
    assert "graphql" in trigger_line
    assert "architect" not in trigger_line
    assert "building" not in trigger_line
    assert "designing" not in trigger_line
    assert "time-subscription" not in trigger_line
    assert "apollo" in trigger_line
    assert "dataloader" in trigger_line
    assert "schema" in trigger_line
    assert "schemas" not in trigger_line
    assert trigger_line.count("schema") == 1


def test_project_dashboard_does_not_surface_broad_modifier_triggers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    skill = tmp_path / ".agentpack" / "skills" / "golang-patterns" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: golang-patterns\n"
        "description: Idiomatic Go patterns, best practices, and conventions for building robust, efficient, and maintainable Go applications.\n"
        "---\n\n",
        encoding="utf-8",
    )

    snapshot = build_project_dashboard_snapshot(tmp_path)

    metadata = snapshot.skills_inventory.rows[0].metadata
    trigger_line = next(item for item in metadata if item.startswith("triggers:"))
    triggers = [item.strip() for item in trigger_line.removeprefix("triggers:").split(",")]
    assert "idiomatic-go" in trigger_line
    assert "go-pattern" in trigger_line
    assert "best-practice" in trigger_line
    assert "robust" not in triggers
    assert "building" not in triggers
    assert "maintainable" not in triggers
    assert "application" not in triggers
