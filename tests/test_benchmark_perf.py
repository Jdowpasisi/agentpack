from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from agentpack.summaries.base import build_all_summaries
from agentpack.core.models import FileInfo


def _budget(local_seconds: float, ci_seconds: float) -> float:
    return ci_seconds if os.getenv("CI") else local_seconds


def _make_files(tmp_path: Path) -> list[FileInfo]:
    files: list[FileInfo] = []
    for i in range(5000):
        content = "".join(f"def fn_{i}_{j}(): return {j}\n" for j in range(20))
        p = tmp_path / f"file_{i}.py"
        p.write_text(content, encoding="utf-8")
        files.append(
            FileInfo(
                path=f"file_{i}.py",
                abs_path=p,
                hash=hashlib.md5(content.encode()).hexdigest(),
                language="python",
                size_bytes=len(content.encode()),
                estimated_tokens=50,
            )
        )
    return files


@pytest.mark.slow
def test_build_all_summaries_cold_5000_files(tmp_path: Path) -> None:
    files = _make_files(tmp_path)
    start = time.perf_counter()
    result = build_all_summaries(files, tmp_path)
    elapsed = time.perf_counter() - start
    assert len(result) == 5000
    budget = _budget(local_seconds=10, ci_seconds=20)
    assert elapsed < budget, f"cold run took {elapsed:.2f}s, expected < {budget:g}s"


@pytest.mark.slow
def test_build_all_summaries_warm_cache_5000_files(tmp_path: Path) -> None:
    files = _make_files(tmp_path)
    build_all_summaries(files, tmp_path)  # prime the cache
    start = time.perf_counter()
    result = build_all_summaries(files, tmp_path)
    elapsed = time.perf_counter() - start
    assert len(result) == 5000
    budget = _budget(local_seconds=2, ci_seconds=5)
    assert elapsed < budget, f"warm run took {elapsed:.2f}s, expected < {budget:g}s"
