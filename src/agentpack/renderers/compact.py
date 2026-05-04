from __future__ import annotations

from datetime import datetime, timezone

from agentpack.core.models import ContextPack, SelectedFile


def _format_file_entry(sf: SelectedFile) -> str:
    """Format a single selected file entry for the compact format."""
    lines: list[str] = [sf.path]
    lines.append(f"score: {int(sf.score)}")
    lines.append(f"include: {sf.include_mode}")
    if sf.reasons:
        lines.append(f"why: {', '.join(sf.reasons)}")
    if sf.symbols:
        symbol_names = ", ".join(s.name for s in sf.symbols)
        lines.append(f"symbols: {symbol_names}")
    return "\n".join(lines)


def render_compact(pack: ContextPack) -> str:
    """Render a ContextPack into a structured compact format."""
    selected: list[SelectedFile] = []
    deps: list[SelectedFile] = []

    for sf in pack.selected_files:
        if sf.include_mode in ("full", "symbols"):
            selected.append(sf)
        else:
            deps.append(sf)

    now = datetime.now(timezone.utc).isoformat()
    sections: list[str] = []

    sections.append("# AgentPack Context")
    sections.append("")
    sections.append(f"task: {pack.task}")
    sections.append(f"mode: {pack.mode}")
    sections.append(f"budget: {pack.token_estimate}/{pack.budget}")
    sections.append(f"generated: {now}")
    sections.append("")

    sections.append("## selected")
    sections.append("")
    if selected:
        for sf in selected:
            sections.append(_format_file_entry(sf))
            sections.append("")
    else:
        sections.append("(none)")
        sections.append("")

    sections.append("## deps")
    sections.append("")
    if deps:
        for sf in deps:
            lines: list[str] = [sf.path]
            lines.append(f"score: {int(sf.score)}")
            lines.append("include: summary")
            if sf.reasons:
                lines.append(f"why: {sf.reasons[0]}")
            sections.append("\n".join(lines))
            sections.append("")
    else:
        sections.append("(none)")
        sections.append("")

    sections.append("## instructions")
    sections.append("")
    sections.append("- Prefer selected files first.")
    sections.append("- If task changes significantly, update `.agentpack/task.md`.")
    sections.append("- Run `agentpack session refresh` if context seems stale.")
    sections.append("")

    return "\n".join(sections)
