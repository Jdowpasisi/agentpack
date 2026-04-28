from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SnapshotDiff:
    added: list[str]
    modified: list[str]
    deleted: list[str]
    unchanged: list[str]


def diff_snapshots(
    old: dict[str, Any] | None,
    new: dict[str, Any],
) -> SnapshotDiff:
    new_files: dict[str, str] = {
        p: info["hash"] for p, info in new.get("files", {}).items() if info.get("hash")
    }

    if old is None:
        return SnapshotDiff(
            added=sorted(new_files),
            modified=[],
            deleted=[],
            unchanged=[],
        )

    old_files: dict[str, str] = {
        p: info["hash"] for p, info in old.get("files", {}).items() if info.get("hash")
    }

    added = sorted(p for p in new_files if p not in old_files)
    deleted = sorted(p for p in old_files if p not in new_files)
    modified = sorted(p for p in new_files if p in old_files and new_files[p] != old_files[p])
    unchanged = sorted(p for p in new_files if p in old_files and new_files[p] == old_files[p])

    return SnapshotDiff(added=added, modified=modified, deleted=deleted, unchanged=unchanged)
