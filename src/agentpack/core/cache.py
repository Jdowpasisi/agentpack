from __future__ import annotations

import json
from pathlib import Path

from agentpack.core.models import FileSummary


def _cache_key(path: str, file_hash: str, provider: str, schema_version: int) -> str:
    import hashlib
    raw = f"{path}|{file_hash}|{provider}|{schema_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_dir(root: Path) -> Path:
    return root / ".agentpack" / "cache"


def load_summary(
    root: Path, path: str, file_hash: str, provider: str = "offline", schema_version: int = 1
) -> FileSummary | None:
    key = _cache_key(path, file_hash, provider, schema_version)
    cache_file = _cache_dir(root) / f"{key}.json"
    if not cache_file.exists():
        return None
    return FileSummary.model_validate_json(cache_file.read_text())


def save_summary(root: Path, summary: FileSummary) -> None:
    key = _cache_key(summary.path, summary.hash, summary.provider, summary.schema_version)
    cache_dir = _cache_dir(root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{key}.json"
    cache_file.write_text(summary.model_dump_json(indent=2))
