from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EVENTS_PATH = ".agentpack/session-events.jsonl"


def record_event(
    root: Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    output_path: str = DEFAULT_EVENTS_PATH,
) -> None:
    path = root / output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(payload or {}),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")


def read_events(root: Path, *, output_path: str = DEFAULT_EVENTS_PATH, limit: int = 200) -> list[dict[str, Any]]:
    path = root / output_path
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(event.get("type") or "unknown") for event in events)
    packed_tokens = sum(int(event.get("packed_tokens") or 0) for event in events if event.get("type") == "pack")
    raw_tokens = sum(int(event.get("raw_tokens") or 0) for event in events if event.get("type") == "pack")
    retrievals = counts.get("retrieve", 0)
    output_compressions = counts.get("compress_output", 0)
    return {
        "events": len(events),
        "counts": dict(counts),
        "packed_tokens": packed_tokens,
        "raw_tokens": raw_tokens,
        "estimated_saved_tokens": max(0, raw_tokens - packed_tokens),
        "retrievals": retrievals,
        "output_compressions": output_compressions,
    }
