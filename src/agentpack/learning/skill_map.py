from __future__ import annotations

import json
from pathlib import Path

from agentpack.learning.models import SkillEvidence, SkillProgress


def update_skill_map(path: Path, evidence: list[SkillEvidence]) -> dict:
    payload = _read_payload(path)
    skills = payload.setdefault("skills", {})
    for item in evidence:
        current = SkillProgress.model_validate(
            skills.get(item.skill, {"skill": item.skill, "task_count": 0, "evidence": []})
        )
        current.task_count += 1
        current.last_task = item.task
        current.evidence.insert(0, item)
        current.evidence = current.evidence[:10]
        skills[item.skill] = current.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _read_payload(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "skills": {}}
    return json.loads(path.read_text(encoding="utf-8"))
