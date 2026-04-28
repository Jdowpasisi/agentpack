from __future__ import annotations

from pathlib import Path

from agentpack.core.models import FileInfo, FileSummary
from agentpack.core import cache as summary_cache
from agentpack.summaries import offline


_LLM_PROVIDERS = {"claude", "openai"}


def get_or_build_summary(fi: FileInfo, root: Path, provider: str = "offline") -> FileSummary:
    if fi.hash is None:
        return offline.summarize(fi.path, fi.abs_path, fi.language, "")

    cached = summary_cache.load_summary(root, fi.path, fi.hash, provider)
    if cached:
        return cached

    if provider in _LLM_PROVIDERS:
        from agentpack.summaries import llm as llm_mod
        summary = llm_mod.summarize(fi.path, fi.abs_path, fi.language, fi.hash, provider=provider)
    else:
        summary = offline.summarize(fi.path, fi.abs_path, fi.language, fi.hash)

    summary_cache.save_summary(root, summary)
    return summary


def build_all_summaries(
    files: list[FileInfo],
    root: Path,
    provider: str = "offline",
) -> dict[str, FileSummary]:
    result: dict[str, FileSummary] = {}
    for fi in files:
        if fi.ignored or fi.binary:
            continue
        result[fi.path] = get_or_build_summary(fi, root, provider)
    return result
