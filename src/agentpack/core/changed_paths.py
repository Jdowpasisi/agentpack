from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _ledger_path(root: Path) -> Path:
    return root / ".agentpack" / "changed_paths.json"


def record_changed_paths(root: Path, paths: set[str] | list[str], *, source: str) -> None:
    normalized = sorted({path.replace("\\", "/").strip() for path in paths if path.strip()})
    if not normalized:
        return
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_changed_paths(root)
    merged = sorted(existing | set(normalized))
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "paths": merged,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_changed_paths(root: Path) -> set[str]:
    path = _ledger_path(root)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw_paths = data.get("paths") if isinstance(data, dict) else []
    if not isinstance(raw_paths, list):
        return set()
    return {str(item).replace("\\", "/").strip() for item in raw_paths if str(item).strip()}


def clear_changed_paths(root: Path) -> None:
    try:
        _ledger_path(root).unlink(missing_ok=True)
    except OSError:
        pass
