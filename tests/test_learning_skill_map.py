import json

from agentpack.learning.models import SkillEvidence
from agentpack.learning.skill_map import update_skill_map


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
    assert item["last_task"] == "Add AgentPack Learn"
    assert item["evidence"][0]["evidence_files"] == ["src/agentpack/commands/learn.py"]
    assert "lines_changed" not in item
    assert "productivity_score" not in item
