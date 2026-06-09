from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agentpack.learning.models import LearningReport


def record_learning_feedback(path: Path, report: LearningReport, feedback: str, note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": report.task,
        "scope": report.scope,
        "feedback": feedback,
        "note": note,
        "concepts": report.concepts,
        "source_files": [source.path for source in report.source_files],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
