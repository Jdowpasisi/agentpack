from __future__ import annotations

from collections import defaultdict
import json

from agentpack.core.models import ContextPack, OmittedRelevantFile, SelectedFile, Symbol
from agentpack.core.command_surface import refresh_commands
from agentpack.core.pack_handoff import build_pack_handoff
from agentpack.core.token_estimator import estimate_tokens


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


def _selected_file_tokens(sf: SelectedFile) -> int:
    if sf.content:
        return estimate_tokens(sf.content)
    if sf.include_mode == "summary":
        return estimate_tokens(sf.summary) if sf.summary else 50
    parts: list[str] = []
    if sf.summary:
        parts.append(sf.summary)
    for sym in sf.symbols:
        if sym.signature:
            parts.append(sym.signature)
    return estimate_tokens("\n".join(parts)) if parts else 50


def _omitted_action(item: OmittedRelevantFile) -> str:
    reason_text = " ".join(item.reasons).lower()
    path = item.path.lower()
    if "reverse dependency" in reason_text or "caller" in reason_text:
        return "inspect caller"
    if "related test" in reason_text or "test for" in reason_text or path.startswith(("tests/", "test/")):
        return "inspect test"
    if any(part in path for part in ("route", "routes", "controller", "api/")):
        return "inspect API contract"
    if any(part in path for part in ("schema", "migration", "model", "models")):
        return "inspect data contract"
    if "config" in reason_text or any(part in path for part in ("config", ".env", "deploy", "settings")):
        return "inspect config"
    return "inspect if touched"


def _omitted_reason(item: OmittedRelevantFile) -> str:
    if item.reasons:
        return item.reasons[0]
    return item.omission_reason


def _omitted_relevant_lines(pack: ContextPack, limit: int = 10) -> list[str]:
    if not pack.omitted_relevant_files:
        return []
    risk_rank = {"high": 0, "medium": 1, "low": 2}
    omitted = sorted(
        pack.omitted_relevant_files,
        key=lambda item: (risk_rank.get(item.risk, 2), -item.score, item.path),
    )[:limit]
    lines = ["## Omitted But Relevant Files", ""]
    lines.append("These files matched the task but were not included due to token budget.")
    lines.append(
        "Do not assume omitted relevant files are safe. If a selected function/class has omitted callers, "
        "tests, routes, schemas, or configs, inspect them before finalizing the fix."
    )
    lines.append(
        "Before finalizing changes, inspect high-risk omitted files if your fix changes shared behavior, "
        "function signatures, data models, API contracts, or side effects."
    )
    lines.append("")
    lines.append("| # | File | Risk | Score | Why | Suggested action |")
    lines.append("|---:|---|---|---:|---|---|")
    for index, item in enumerate(omitted, start=1):
        lines.append(
            f"| {index} | `{item.path}` | {item.risk.upper()} | {item.score:.0f} | "
            f"{_omitted_reason(item)} | {_omitted_action(item)} |"
        )
    hidden = len(pack.omitted_relevant_files) - len(omitted)
    if hidden > 0:
        lines.append("")
        lines.append(f"_+{hidden} more omitted relevant file(s) hidden._")
    lines.append("")
    return lines


def _receipt_lines(pack: ContextPack) -> list[str]:
    included = [r for r in pack.receipts if r.action != "excluded"]
    excluded = [r for r in pack.receipts if r.action == "excluded"]
    lines: list[str] = []

    for r in included:
        lines.append(f"- `{r.path}` {r.action} because {r.reason}")

    by_reason: dict[str, list[str]] = defaultdict(list)
    for r in excluded:
        by_reason[r.reason].append(r.path)

    for reason, paths in sorted(by_reason.items(), key=lambda item: (-len(item[1]), item[0])):
        shown = ", ".join(f"`{path}`" for path in paths[:10])
        suffix = f"; top {min(10, len(paths))}: {shown}" if shown else ""
        if len(paths) > 10:
            suffix += f"; +{len(paths) - 10} more"
        lines.append(f"- {len(paths)} file(s) excluded because {reason}{suffix}")

    return lines


def _freshness_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _execution_state_lines(state: dict[str, object]) -> list[str]:
    task = state.get("task") if isinstance(state.get("task"), dict) else {}
    git = state.get("git") if isinstance(state.get("git"), dict) else {}
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    checklist = task.get("checklist") if isinstance(task.get("checklist"), dict) else {}
    lines = ["## Execution State", ""]
    lines.append(f"- **Task status:** {task.get('status') or 'unknown'}")
    if task.get("summary"):
        lines.append(f"- **Task summary:** {task['summary']}")
    if task.get("state_file"):
        lines.append(f"- **Task state file:** `{task['state_file']}`")
    if checklist:
        lines.append(
            "- **Checklist:** "
            f"{checklist.get('done', 0)} done, {checklist.get('open', 0)} open, {checklist.get('blocked', 0)} blocked"
        )
    branch = git.get("branch") or "unknown"
    sha = str(git.get("sha") or "")[:12] or "unknown"
    lines.append(f"- **Git:** {branch} @ {sha}")
    lines.append(
        "- **Working tree:** "
        f"{git.get('staged_count', 0)} staged, {git.get('unstaged_count', 0)} unstaged, "
        f"{git.get('untracked_count', 0)} untracked"
    )
    lines.append(f"- **Remote delta:** ahead {git.get('ahead', 0)}, behind {git.get('behind', 0)}")
    lines.append(f"- **Runtime:** docker={runtime.get('docker', 'unknown')}, compose={runtime.get('compose_file') or 'none'}")
    lines.append("")
    return lines


def _concurrent_context_lines(context: dict[str, object]) -> list[str]:
    conflicts = context.get("conflicts") if isinstance(context.get("conflicts"), list) else []
    conflict_count = context.get("conflict_count", len(conflicts))
    if not context.get("thread_id") and not conflicts and not conflict_count:
        return []
    lines = ["## Concurrent Context", ""]
    lines.append(f"- **Current thread:** {context.get('thread_id') or 'none'}")
    lines.append(f"- **Active threads:** {context.get('active_threads', 0)}")
    if conflict_count and not conflicts:
        lines.append(f"- **Overlap warning:** {conflict_count} conflicting thread(s).")
    elif conflicts:
        lines.append("- **Overlap warning:** coordinate before editing overlapping files or use a separate worktree.")
        for item in conflicts[:5]:
            if not isinstance(item, dict):
                continue
            overlap = item.get("overlap") if isinstance(item.get("overlap"), list) else []
            shown = ", ".join(f"`{path}`" for path in overlap[:6])
            more = int(item.get("overlap_count") or len(overlap)) - min(len(overlap), 6)
            suffix = f"; +{more} more" if more > 0 else ""
            lines.append(
                f"- `{item.get('thread_id')}` ({item.get('status') or 'unknown'}): "
                f"{item.get('task') or 'no task'}; overlap {shown}{suffix}"
            )
    else:
        lines.append("- **Overlap warning:** none detected.")
    lines.append("")
    return lines


def _pack_handoff_lines(pack: ContextPack) -> list[str]:
    handoff = build_pack_handoff(pack)
    budget = handoff["budget"]
    selected = handoff["selected"]
    omitted = handoff["omitted_relevant"]
    freshness = handoff["freshness"]
    lines = ["## Pack Handoff", ""]
    lines.append(f"- **Recommended next action:** `{handoff['recommended_action']}`")
    lines.append(f"- **Reason:** {handoff['reason']}")
    lines.append(
        "- **Budget:** "
        f"{budget['rendered_tokens']:,}/{budget['target_tokens']:,} tokens"
        + (" (budget pressure)" if budget["pressure"] else "")
    )
    lines.append(f"- **Selected files:** {selected['files']} ({selected['tests']} test file(s))")
    lines.append(
        f"- **Omitted relevant files:** {omitted['files']} total, {omitted['high_risk']} high-risk"
    )
    if omitted["top"]:
        lines.append("- **Inspect first:** " + ", ".join(f"`{path}`" for path in omitted["top"]))
    if freshness["refresh_required"]:
        warning_text = "; ".join(str(item) for item in freshness["warnings"]) or "refresh required"
        lines.append(f"- **Freshness:** refresh required — {warning_text}")
    else:
        lines.append("- **Freshness:** no refresh gate fired")
    lines.append("")
    return lines


def _machine_freshness_block(pack: ContextPack) -> str:
    stale_task = _has_task_stale_warning(pack)
    refresh_required = pack.stale or stale_task
    fields = {
        "active_context": "mcp",
        "fallback_context": "markdown",
        "packed_task": pack.task,
        "cwd": pack.freshness.get("cwd", ""),
        "git_root": pack.freshness.get("git_root", ""),
        "worktree_path": pack.freshness.get("worktree_path", ""),
        "git_branch": pack.freshness.get("git_branch", ""),
        "agentpack_version": pack.freshness.get("agentpack_version", ""),
        "source_command": pack.freshness.get("source_command", ""),
        "task_hash": pack.freshness.get("packed_task_hash") or pack.freshness.get("task_hash") or "",
        "task_md_hash": pack.freshness.get("task_md_hash", ""),
        "snapshot_root_hash": pack.freshness.get("snapshot_root_hash", ""),
        "generated_at": pack.freshness.get("generated_at", ""),
        "stale_task_context": stale_task,
        "refresh_required": refresh_required,
        "mcp_refresh_tool": "agentpack_get_context",
        "cli_refresh_command": refresh_commands(pack.agent).primary,
    }
    return "<!-- agentpack:freshness\n" + json.dumps(fields, indent=2, sort_keys=True) + "\n-->"


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


def _stable_prefix_lines(agent_name: str) -> list[str]:
    return [
        f"# AgentPack Context for {agent_name}",
        "",
        "<!-- agentpack:stable-prefix:start -->",
        "",
        f"## Instructions for {agent_name}",
        "",
        (
            "This is a task-focused context pack. Act on it immediately:\n\n"
            "1. **Orient** — identify the changed files and key symbols relevant to the task.\n"
            "2. **Diagnose or plan** — find the root cause (bug fix) or outline the approach (feature).\n"
            "3. **Work** — edit files, write code, fix the issue. Do not wait for more instructions.\n\n"
            "Priority order: changed files → keyword matches → dependencies → summaries.\n"
            "Modes: `full` source, `diff` hunks, `symbols` or `skeleton` interfaces, `summary` brief context.\n"
            "If this pack's task does not match the user's current task, write the new task to "
            "`.agentpack/task.md`, run `agentpack pack --task auto`, re-read the context, then proceed. "
            "If the pack looks stale or from another worktree, do not trust old selected files."
        ),
        "",
        "<!-- agentpack:stable-prefix:end -->",
        "",
    ]


def render_claude(pack: ContextPack) -> str:
    sections: list[str] = _stable_prefix_lines("Claude")

    sections.append(_machine_freshness_block(pack))
    sections.append("")

    if pack.stale:
        sections.append("> **Warning:** This context pack may be stale. Run `agentpack pack` to regenerate.")
        sections.append("")
    if _has_task_stale_warning(pack):
        sections.append(
            "> **STALE TASK CONTEXT:** `.agentpack/task.md` does not match this packed context. "
            "Do not trust selected files until refreshed. Run `agentpack pack --task auto`, "
            "or call `agentpack_pack_context()` / `agentpack_get_context()` before using this pack."
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
            ("AgentPack version", "agentpack_version"),
            ("Source command", "source_command"),
            ("CWD", "cwd"),
            ("Git root", "git_root"),
            ("Worktree path", "worktree_path"),
            ("Git branch", "git_branch"),
            ("Git SHA", "git_sha"),
            ("Task class", "task_class"),
            ("Task source", "task_source"),
            ("Changed-file source", "changed_files_source"),
            ("Scan mode", "scan_mode"),
            ("Scan rehashed files", "scan_rehashed_count"),
            ("Scan reused files", "scan_reused_count"),
            ("Full scan reason", "full_scan_reason"),
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

    if pack.execution_state:
        sections.extend(_execution_state_lines(pack.execution_state))

    if pack.concurrent_context:
        sections.extend(_concurrent_context_lines(pack.concurrent_context))

    sections.extend(_pack_handoff_lines(pack))

    if pack.agent_lessons:
        sections.append("## Agent Lessons From Prior Work")
        sections.append("")
        sections.append(pack.agent_lessons)
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

    if pack.selected_files:
        sections.append("## Largest Token Consumers")
        sections.append("")
        sections.append("| File | Mode | Tokens |")
        sections.append("|---|---|---:|")
        for sf in sorted(pack.selected_files, key=_selected_file_tokens, reverse=True)[:10]:
            sections.append(f"| `{sf.path}` | {sf.include_mode} | {_selected_file_tokens(sf):,} |")
        sections.append("")

    if pack.receipts:
        sections.append("## Context Receipts")
        sections.append("")
        sections.extend(_receipt_lines(pack))
        sections.append("")

    sections.extend(_omitted_relevant_lines(pack))

    sections.append("## File Context")
    sections.append("")
    for sf in pack.selected_files:
        sections.append(_file_section(sf))
        sections.append("")

    return "\n".join(sections)


def render_generic(pack: ContextPack) -> str:
    return (
        render_claude(pack)
        .replace("# AgentPack Context for Claude", "# AgentPack Context")
        .replace("## Instructions for Claude", "## Instructions for Agent")
    )


def render_antigravity(pack: ContextPack) -> str:
    """Render context as an Antigravity SKILL.md with required frontmatter."""
    body = (
        render_claude(pack)
        .replace("# AgentPack Context for Claude", "# AgentPack Context")
        .replace("## Instructions for Claude", "## Instructions for Agent")
    )
    frontmatter = (
        "---\n"
        "name: agentpack\n"
        "description: AgentPack task-focused repo context. Activates when working on a coding task in this repository.\n"
        "---\n\n"
    )
    return frontmatter + body
