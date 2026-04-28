from __future__ import annotations

from pathlib import Path

from agentpack.core.models import FileSummary
from agentpack.analysis.symbols import extract_symbols


_SYSTEM_PROMPT = """\
You are a code summarizer. Given source code, produce a concise summary (3-5 sentences) covering:
- What this file does and its likely responsibility
- Key classes, functions, or exports it provides
- Important dependencies or side effects

Be factual and terse. No filler phrases."""

_MAX_INPUT_CHARS = 12000


def summarize_with_claude(
    path: str,
    abs_path: Path,
    language: str | None,
    file_hash: str,
    model: str = "claude-haiku-4-5-20251001",
) -> FileSummary:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Install agentpack[llm] to use LLM summaries: pip install 'agentpack[llm]'")

    try:
        content = abs_path.read_text(errors="replace")[:_MAX_INPUT_CHARS]
    except OSError:
        content = ""

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=300,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"File: {path}\nLanguage: {language or 'unknown'}\n\n```\n{content}\n```",
            }
        ],
    )
    summary_text = message.content[0].text if message.content else ""

    symbols = extract_symbols(abs_path, language)

    return FileSummary(
        path=path,
        hash=file_hash,
        language=language,
        provider="claude",
        schema_version=1,
        summary=summary_text,
        imports=[],
        symbols=symbols,
    )


def summarize(
    path: str,
    abs_path: Path,
    language: str | None,
    file_hash: str,
    provider: str = "claude",
    model: str | None = None,
) -> FileSummary:
    if provider == "claude":
        return summarize_with_claude(
            path, abs_path, language, file_hash,
            model=model or "claude-haiku-4-5-20251001",
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
