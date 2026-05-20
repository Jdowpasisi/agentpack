from __future__ import annotations

from agentpack.core.models import ContextPack, SelectedFile, Symbol


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


def _freshness_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _file_section(sf: SelectedFile) -> str:
    # Content is already redacted at materialization time (context_pack.select_files)
    parts = [f"### {sf.path}", ""]
    parts.append(f"Included as: **{sf.include_mode}**")
    parts.append("")
    if sf.reasons:
        parts.append("Reasons:")
        for r in sf.reasons:
            parts.append(f"- {r}")
        parts.append("")

    if sf.include_mode in ("full", "diff", "symbols", "skeleton") and sf.content:
        parts.append("```" + _lang_fence(sf.language))
        parts.append(sf.content)
        parts.append("```")
        if sf.redaction_warnings:
            types = ", ".join(
                w.split(": ", 1)[1] if ": " in w else w for w in sf.redaction_warnings
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


def _has_task_stale_warning(pack: ContextPack) -> bool:
    warnings = " ".join(pack.freshness_warnings).lower()
    return ".agentpack/task.md differs" in warnings or (
        "packed task" in warnings and "task.md" in warnings
    )


def render_claude(pack: ContextPack) -> str:
    sections: list[str] = []

    sections.append("# AgentPack Context for Claude")
    sections.append("")

    if pack.stale:
        sections.append("> **Warning:** This context pack may be stale. Run `agentpack pack` to regenerate.")
        sections.append("")
    if _has_task_stale_warning(pack):
        sections.append(
            "> **STALE TASK CONTEXT:** `.agentpack/task.md` does not match this packed context. "
            "Refresh with `agentpack pack --task auto` or call `agentpack_pack_context()` before using selected files."
        )
        sections.append("")

    sections.append("## Task")
    sections.append("")

    if pack.freshness or pack.freshness_warnings:
        sections.append("## Freshness")
        sections.append("")
        if pack.freshness_warnings:
            sections.append("> **Refresh recommended:** " + " ".join(pack.freshness_warnings))
            sections.append("")
        for label, key in (
            ("Generated", "generated_at"),
            ("Git branch", "git_branch"),
            ("Git SHA", "git_sha"),
            ("Task class", "task_class"),
            ("Task source", "task_source"),
            ("Changed-file source", "changed_files_source"),
            ("Workspaces", "workspace_roots"),
            ("Snapshot hash", "snapshot_root_hash"),
            ("Dirty files at pack time", "dirty_files_count"),
        ):
            value = pack.freshness.get(key)
            if value is not None:
                sections.append(f"- **{label}:** {_freshness_value(value)}")
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
        "Files marked `full` contain complete source. Files marked `diff` contain relevant changed hunks. "
        "Files marked `symbols` contain relevant function/class bodies. Files marked `skeleton` contain imports/signatures. "
        "Files marked `summary` are unchanged context.\n"
        "If this pack's task does not match the user's current task, write the new task to "
        "`.agentpack/task.md`, run `agentpack pack --task auto`, re-read the context, then proceed. "
        "If the pack looks stale (changed files list is empty but you expect changes), refresh the pack before editing."
    )
    sections.append("")

    sections.append("## Token Stats")
    sections.append("")
    sections.append(f"Raw repo tokens: {pack.raw_repo_tokens:,}")
    sections.append(f"After ignore: {pack.after_ignore_tokens:,}")
    sections.append(f"Packed tokens: {pack.token_estimate:,}")
    sections.append(f"Estimated saving: {pack.estimated_savings_percent:.1f}%")
    sections.append("")

    if pack.delta_summary:
        sections.append("## Delta Since Last Pack")
        sections.append("")
        sections.append(pack.delta_summary)
        sections.append("")

    if pack.repo_map:
        sections.append("## Repo Map")
        sections.append("")
        sections.append(pack.repo_map)
        sections.append("")

    if pack.redaction_warnings:
        sections.append("## Security")
        sections.append("")
        sections.append("> The following secrets were redacted before packing:")
        sections.append("")
        for w in pack.redaction_warnings:
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


def render_antigravity(pack: ContextPack) -> str:
    """Render context as an Antigravity SKILL.md with required frontmatter."""
    body = render_claude(pack).replace(
        "# AgentPack Context for Claude", "# AgentPack Context"
    )
    frontmatter = (
        "---\n"
        "name: agentpack\n"
        "description: AgentPack task-focused repo context. Activates when working on a coding task in this repository.\n"
        "---\n\n"
    )
    return frontmatter + body
