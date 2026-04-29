from __future__ import annotations

from agentpack.core.models import ContextPack, SelectedFile, Symbol
from agentpack.core.redactor import redact_secrets


def _lang_fence(lang: str | None) -> str:
    return lang or ""


def _symbols_block(symbols: list[Symbol], lang: str | None) -> str:
    if not symbols:
        return ""
    lines = ["```" + _lang_fence(lang)]
    for s in symbols:
        if s.signature:
            lines.append(s.signature)
            if s.summary:
                lines.append(f"    # {s.summary}")
    lines.append("```")
    return "\n".join(lines)


def _file_section(sf: SelectedFile) -> str:
    parts = [f"### {sf.path}", ""]
    parts.append(f"Included as: **{sf.include_mode}**")
    parts.append("")
    if sf.reasons:
        parts.append("Reasons:")
        for r in sf.reasons:
            parts.append(f"- {r}")
        parts.append("")

    if sf.include_mode == "full" and sf.content:
        content, redact_warnings = redact_secrets(sf.content, sf.path)
        parts.append("```" + _lang_fence(sf.language))
        parts.append(content)
        parts.append("```")
        if redact_warnings:
            types = ", ".join(
                w.split(": ", 1)[1] if ": " in w else w for w in redact_warnings
            )
            parts.append(f"> ⚠ Secrets redacted: {types}")

    elif sf.include_mode == "symbols" and sf.content:
        content, redact_warnings = redact_secrets(sf.content, sf.path)
        parts.append("```" + _lang_fence(sf.language))
        parts.append(content)
        parts.append("```")
        if redact_warnings:
            types = ", ".join(
                w.split(": ", 1)[1] if ": " in w else w for w in redact_warnings
            )
            parts.append(f"> ⚠ Secrets redacted: {types}")

    elif sf.include_mode == "symbols":
        if sf.summary:
            parts.append("Summary:")
            parts.append(sf.summary)
            parts.append("")
        if sf.symbols:
            parts.append("Relevant symbols:")
            parts.append("")
            parts.append(_symbols_block(sf.symbols, sf.language))

    elif sf.include_mode == "summary":
        if sf.summary:
            parts.append("Summary:")
            parts.append(sf.summary)

    return "\n".join(parts)


def _collect_redaction_warnings(pack: ContextPack) -> list[str]:
    """Return all redaction warnings across all full/symbols files."""
    warnings: list[str] = []
    for sf in pack.selected_files:
        if sf.include_mode in ("full", "symbols") and sf.content:
            _, file_warnings = redact_secrets(sf.content, sf.path)
            warnings.extend(file_warnings)
    return warnings


def render_claude(pack: ContextPack) -> str:
    sections: list[str] = []

    sections.append("# AgentPack Context for Claude")
    sections.append("")

    if pack.stale:
        sections.append("> **Warning:** This context pack may be stale. Run `agentpack pack` to regenerate.")
        sections.append("")

    sections.append("## Task")
    sections.append("")
    sections.append(pack.task)
    sections.append("")

    sections.append("## Instructions for Claude")
    sections.append("")
    sections.append(
        "This is a task-focused context pack. Act on it immediately:\n\n"
        "1. **Orient** — identify the changed files and key symbols relevant to the task.\n"
        "2. **Diagnose or plan** — find the root cause (bug fix) or outline the approach (feature).\n"
        "3. **Work** — edit files, write code, fix the issue. Do not wait for more instructions.\n\n"
        "Priority order: changed files → keyword-matched files → dependencies → summaries.\n"
        "Files marked `full` contain complete source. Files marked `symbols` contain relevant "
        "function/class bodies. Files marked `summary` are unchanged context.\n"
        "If the pack looks stale (changed files list is empty but you expect changes), "
        "ask the user to run `agentpack pack --task \"<task>\"` to refresh."
    )
    sections.append("")

    sections.append("## Token Stats")
    sections.append("")
    sections.append(f"Raw repo tokens: {pack.raw_repo_tokens:,}")
    sections.append(f"After ignore: {pack.after_ignore_tokens:,}")
    sections.append(f"Packed tokens: {pack.token_estimate:,}")
    sections.append(f"Estimated saving: {pack.estimated_savings_percent:.1f}%")
    sections.append("")

    # Redaction summary — list all files that had secrets scrubbed
    redaction_warnings = _collect_redaction_warnings(pack)
    if redaction_warnings:
        sections.append("## Security")
        sections.append("")
        sections.append("> The following secrets were redacted before packing:")
        sections.append("")
        for w in redaction_warnings:
            sections.append(f"- {w}")
        sections.append("")

    sections.append("## Changed Files")
    sections.append("")
    if pack.changed_files:
        for f in pack.changed_files:
            sections.append(f"- {f}")
    else:
        sections.append("_No changed files detected._")
    sections.append("")

    sections.append("## Selected Files")
    sections.append("")
    sections.append("| File | Mode | Score | Why |")
    sections.append("|---|---|---:|---|")
    for sf in pack.selected_files:
        why = sf.reasons[0] if sf.reasons else ""
        sections.append(f"| `{sf.path}` | {sf.include_mode} | {sf.score:.0f} | {why} |")
    sections.append("")

    if pack.receipts:
        sections.append("## Context Receipts")
        sections.append("")
        for r in pack.receipts:
            sections.append(f"- `{r.path}` {r.action} because {r.reason}")
        sections.append("")

    sections.append("## File Context")
    sections.append("")
    for sf in pack.selected_files:
        sections.append(_file_section(sf))
        sections.append("")

    return "\n".join(sections)


def render_generic(pack: ContextPack) -> str:
    return render_claude(pack).replace("# AgentPack Context for Claude", "# AgentPack Context")
