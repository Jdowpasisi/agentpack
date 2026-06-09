import json

from agentpack.learning.models import SkillEvidence
from agentpack.learning.skill_map import apply_skill_feedback, recommend_practice_drills, render_skill_summary, update_skill_map


def test_update_skill_map_accumulates_evidence(tmp_path):
    path = tmp_path / ".agentpack" / "skills-progress.json"
    evidence = [
        SkillEvidence(
            skill="CLI design",
            task="Add AgentPack Learn",
            evidence_files=["src/agentpack/commands/learn.py"],
            confidence=80,
        )
    ]

    update_skill_map(path, evidence)
    update_skill_map(path, evidence)

    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload["skills"]["CLI design"]

    assert item["task_count"] == 2
    assert item["confidence"] >= 80
    assert item["last_task"] == "Add AgentPack Learn"
    assert item["source_paths"] == ["src/agentpack/commands/learn.py"]
    assert item["evidence"][0]["evidence_files"] == ["src/agentpack/commands/learn.py"]
    assert "lines_changed" not in item
    assert "productivity_score" not in item


def test_skill_summary_and_drills_are_developer_learning_views(tmp_path):
    path = tmp_path / ".agentpack" / "skills-progress.json"
    update_skill_map(
        path,
        [
            SkillEvidence(
                skill="CLI design",
                task="Add AgentPack Learn",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=80,
            )
        ],
    )

    summary = render_skill_summary(path)
    drills = recommend_practice_drills(path)

    assert "# AgentPack Skill Memory" in summary
    assert "CLI design" in summary
    assert "Explain CLI design" in drills[0]


def test_apply_skill_feedback_renames_merges_and_suppresses(tmp_path):
    path = tmp_path / ".agentpack" / "skills-progress.json"
    update_skill_map(
        path,
        [
            SkillEvidence(skill="CLI design", task="Task one", evidence_files=["cli.py"], confidence=70),
            SkillEvidence(skill="command UX", task="Task two", evidence_files=["docs/commands.md"], confidence=60),
        ],
    )

    apply_skill_feedback(path, target="command UX", action="merge", replacement="CLI design")
    apply_skill_feedback(path, target="CLI design", action="rename", replacement="CLI workflow")
    apply_skill_feedback(path, target="CLI workflow", action="suppress")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "CLI workflow" in payload["skills"]
    assert payload["skills"]["CLI workflow"]["suppressed"] is True
    assert "command UX" in payload["skills"]["CLI workflow"]["aliases"]
