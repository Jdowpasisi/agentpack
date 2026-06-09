from __future__ import annotations

import html

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


def render_provider_preview_markdown(report: LearningReport) -> str:
    lines = [
        "# AgentPack Provider Preview",
        "",
        "This is the bounded, source-backed learning payload that can be sent to an optional provider.",
        "No provider call is made by this preview.",
        "",
        f"Task: {report.task}",
        f"Scope: {report.scope}",
        "",
        "## Changed File Evidence",
    ]
    for source in report.source_files:
        concepts = ", ".join(source.concepts) if source.concepts else "none"
        lines.append(f"- `{source.path}` ({source.change_kind}) concepts: {concepts}")
    lines.extend(["", "## Concepts"])
    lines.extend(f"- {concept}" for concept in report.concepts)
    lines.extend(["", "## Existing Agent Lessons"])
    if report.agent_lessons:
        lines.extend(f"- {lesson.rule}" for lesson in report.agent_lessons)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def render_drills_markdown(drills: list[str]) -> str:
    lines = ["# AgentPack Practice Drills", ""]
    if not drills:
        lines.append("No skill evidence captured yet.")
    else:
        lines.extend(f"{idx}. {drill}" for idx, drill in enumerate(drills, start=1))
    lines.append("")
    return "\n".join(lines)


def render_quality_markdown(report: LearningReport, score: int, issues: list[str]) -> str:
    lines = [
        "# AgentPack Learning Quality",
        "",
        f"Score: {score}",
        f"Task: {report.task}",
        "",
        "## Issues",
    ]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def render_dashboard_html(report: LearningReport) -> str:
    concepts = "".join(f"<li>{html.escape(concept)}</li>" for concept in report.concepts) or "<li>None detected</li>"
    cards = "".join(
        "<article>"
        f"<h3>{html.escape(card.title)}</h3>"
        f"<p>{html.escape(card.body)}</p>"
        f"<p><strong>Evidence:</strong> {html.escape(', '.join(card.files) or 'none')}</p>"
        "</article>"
        for card in report.learning_cards
    ) or "<p>No learning cards generated.</p>"
    lessons = "".join(
        "<li>"
        f"{html.escape(lesson.rule)}"
        f"<br><small>{html.escape(', '.join(lesson.evidence_files) or 'no evidence')}</small>"
        "</li>"
        for lesson in report.agent_lessons
    ) or "<li>No agent lessons generated.</li>"
    drills = html.escape(report.next_practice or "No next practice generated.")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentPack Learn Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    main {{ max-width: 980px; margin: 0 auto; }}
    header {{ border-bottom: 1px solid #d9dde3; margin-bottom: 24px; }}
    h1, h2, h3 {{ line-height: 1.2; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
    article, section.metric {{ border: 1px solid #d9dde3; border-radius: 8px; padding: 16px; }}
    small {{ color: #5f6368; }}
    code {{ background: #f1f3f4; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>AgentPack Learn Dashboard</h1>
    <p><strong>Task:</strong> {html.escape(report.task)}</p>
    <p><strong>Scope:</strong> {html.escape(report.scope)}</p>
  </header>
  <div class="grid">
    <section class="metric"><h2>Changed Files</h2><p>{len(report.source_files)}</p></section>
    <section class="metric"><h2>Concepts</h2><p>{len(report.concepts)}</p></section>
    <section class="metric"><h2>Agent Lessons</h2><p>{len(report.agent_lessons)}</p></section>
  </div>
  <section><h2>Concepts</h2><ul>{concepts}</ul></section>
  <section><h2>Learning Cards</h2>{cards}</section>
  <section><h2>Agent Lessons</h2><ul>{lessons}</ul></section>
  <section><h2>Next Practice</h2><p>{drills}</p></section>
</main>
</body>
</html>
"""


def render_team_lessons_markdown(report: LearningReport) -> str:
    lines = [
        "# AgentPack Team Lessons",
        "",
        "Opt-in repo lessons derived from changed-file evidence. This export omits personal skill history.",
        "",
        "## Concepts",
    ]
    if report.concepts:
        lines.extend(f"- {concept}" for concept in report.concepts)
    else:
        lines.append("- none")
    lines.extend(["", "## Agent Lessons"])
    if report.agent_lessons:
        for lesson in report.agent_lessons:
            lines.append(f"- {lesson.rule}")
            if lesson.evidence_files:
                lines.append("  Evidence: " + ", ".join(f"`{path}`" for path in lesson.evidence_files))
    else:
        lines.append("- none")
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
