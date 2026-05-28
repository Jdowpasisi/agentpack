from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentpack.core.merkle import root_hash
from agentpack.core.models import FileInfo


SNAPSHOT_VERSION = 1


def _snapshots_dir(root: Path) -> Path:
    return root / ".agentpack" / "snapshots"


def _latest_path(root: Path) -> Path:
    return _snapshots_dir(root) / "latest.json"


def build_snapshot(files: list[FileInfo], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a snapshot from packable FileInfo objects. Skips ignored and binary entries defensively."""
    file_data: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for f in files:
        if f.ignored or f.binary:
            continue
        file_data[f.path] = {
            "hash": f.hash,
            "size_bytes": f.size_bytes,
            "estimated_tokens": f.estimated_tokens,
            "language": f.language,
        }
        if f.hash:
            hashes[f.path] = f.hash

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "root_hash": root_hash(hashes),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": file_data,
    }
    if metadata:
        snapshot["metadata"] = metadata
    return snapshot


def save_snapshot(snapshot: dict[str, Any], root: Path) -> None:
    snapshots_dir = _snapshots_dir(root)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    _latest_path(root).write_text(json.dumps(snapshot, indent=2))


def load_snapshot(root: Path) -> dict[str, Any] | None:
    path = _latest_path(root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
