from __future__ import annotations

from agentpack.learning.models import LearningReport


def learning_report_to_dict(report: LearningReport) -> dict:
    return report.model_dump(mode="json")


def render_agent_lessons_markdown(report: LearningReport) -> str:
    if not report.agent_lessons:
        return "# Agent Lessons\n\nNo agent lessons captured yet.\n"
    lines = ["# Agent Lessons", "", "Use these repo-specific lessons in future AgentPack tasks.", ""]
    for lesson in report.agent_lessons:
        lines.append(f"- {lesson.rule}")
        if lesson.evidence_files:
            lines.append("  Evidence: " + ", ".join(f"`{path}`" for path in lesson.evidence_files))
        if lesson.reason:
            lines.append(f"  Reason: {lesson.reason}")
    lines.append("")
    return "\n".join(lines)


def render_llm_prompt_markdown(report: LearningReport) -> str:
    lines = [
        "# AgentPack Learning Prompt",
        "",
        "Create a source-backed learning summary for this coding task.",
        "Use only the changed-file evidence, concepts, risks, tests, and agent lessons below.",
        "Do not invent files, technologies, or decisions not present here.",
        "",
        render_learning_markdown(report),
    ]
    return "\n".join(lines)


def render_pr_comment_markdown(report: LearningReport) -> str:
    lines = ["## Learning Summary", ""]
    lines.extend(report.summary[:3])
    if report.concepts:
        lines.extend(["", "### Concepts"])
        lines.extend(f"- {concept}" for concept in report.concepts[:5])
    if report.risks:
        lines.extend(["", "### Review Risks"])
        lines.extend(f"- {risk}" for risk in report.risks[:3])
    if report.next_practice:
        lines.extend(["", "### Next Practice", report.next_practice])
    lines.append("")
    return "\n".join(lines)


def render_learning_markdown(report: LearningReport) -> str:
    lines: list[str] = [
        "# AgentPack Learning Summary",
        "",
        f"**Task:** {report.task}",
        f"**Scope:** {report.scope}",
    ]
    if report.since:
        lines.append(f"**Since:** `{report.since}`")
    lines.extend(["", "## Summary"])
    lines.extend(f"- {item}" for item in report.summary)
    lines.extend(["", "## Changed Files"])
    for source in report.source_files:
        concepts = ", ".join(source.concepts) if source.concepts else "none detected"
        lines.append(f"- `{source.path}` ({source.change_kind}) - {source.why} Concepts: {concepts}.")
    lines.extend(["", "## Concepts"])
    lines.extend(f"- {concept}" for concept in report.concepts)
    lines.extend(["", "## Decisions"])
    lines.extend(f"- {decision}" for decision in report.decisions)
    lines.extend(["", "## Risks"])
    lines.extend(f"- {risk}" for risk in report.risks)
    lines.extend(["", "## Tests"])
    lines.extend(f"- {test}" for test in report.tests)
    lines.extend(["", "## Skill Evidence"])
    for item in report.skill_evidence:
        files = ", ".join(f"`{path}`" for path in item.evidence_files) if item.evidence_files else "no changed file evidence"
        lines.append(f"- {item.skill}: confidence {item.confidence}; files: {files}")
    lines.extend(["", "## Learning Cards"])
    for card in report.learning_cards:
        lines.append(f"### {card.title}")
        lines.append(card.body)
        if card.files:
            lines.append("Files: " + ", ".join(f"`{path}`" for path in card.files))
        lines.append("")
    lines.extend(["## Agent Lessons"])
    for lesson in report.agent_lessons:
        lines.append(f"- {lesson.rule}")
        if lesson.evidence_files:
            lines.append("  Evidence: " + ", ".join(f"`{path}`" for path in lesson.evidence_files))
        if lesson.reason:
            lines.append(f"  Reason: {lesson.reason}")
    lines.append("")
    lines.extend(["## Quiz"])
    for idx, item in enumerate(report.quiz, start=1):
        lines.append(f"{idx}. {item.question}")
        lines.append(f"   - Answer: {item.answer}")
    lines.extend(["", "## Next Practice", report.next_practice, ""])
    return "\n".join(lines)
