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
    concepts = "".join(f'<span class="chip">{html.escape(concept)}</span>' for concept in report.concepts) or '<span class="muted">None detected</span>'
    cards = "".join(
        '<article class="learning-card">'
        f"<h3>{html.escape(card.title)}</h3>"
        f"<p>{html.escape(card.body)}</p>"
        f'<p class="evidence"><strong>Evidence</strong><br>{_file_chips(card.files)}</p>'
        "</article>"
        for card in report.learning_cards
    ) or '<p class="muted">No learning cards generated.</p>'
    lessons = "".join(
        "<li>"
        f"<strong>{html.escape(lesson.rule)}</strong>"
        f'<br><small>{html.escape(", ".join(lesson.evidence_files) or "no evidence")}</small>'
        "</li>"
        for lesson in report.agent_lessons
    ) or "<li>No agent lessons generated.</li>"
    source_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(source.path)}</code></td>"
        f"<td>{html.escape(source.change_kind)}</td>"
        f"<td>{html.escape(source.why)}</td>"
        f"<td>{_file_chips(source.concepts)}</td>"
        "</tr>"
        for source in report.source_files
    ) or '<tr><td colspan="4">No changed file evidence found.</td></tr>'
    risks = "".join(f"<li>{html.escape(risk)}</li>" for risk in report.risks) or "<li>No risks captured.</li>"
    tests = "".join(f"<li>{html.escape(test)}</li>" for test in report.tests) or "<li>No tests captured.</li>"
    drills = html.escape(report.next_practice or "No next practice generated.")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentPack Learn Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --panel-soft: #f9fafb;
      --border: #d8dee6;
      --text: #171b21;
      --muted: #5b6472;
      --accent: #2457c5;
      --accent-bg: #eaf0ff;
      --code: #eef2f6;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
    .topbar {{ position: sticky; top: 0; z-index: 2; background: rgba(255,255,255,0.96); border-bottom: 1px solid var(--border); backdrop-filter: blur(10px); }}
    .topbar-inner {{ max-width: 1120px; margin: 0 auto; padding: 10px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .brand {{ font-weight: 700; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    nav a {{ color: var(--muted); text-decoration: none; font-size: 13px; padding: 5px 8px; border-radius: 6px; }}
    nav a:hover {{ background: var(--panel-soft); color: var(--text); }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    header.hero {{ padding: 24px 0 22px; display: grid; grid-template-columns: minmax(0, 1fr) 240px; gap: 24px; align-items: end; }}
    h1, h2, h3 {{ line-height: 1.2; margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 32px; font-weight: 760; }}
    h2 {{ font-size: 18px; font-weight: 720; }}
    h3 {{ font-size: 15px; font-weight: 680; }}
    section {{ margin: 18px 0; }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 8px; }}
    .subtitle {{ color: var(--muted); margin: 10px 0 0; max-width: 760px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px; min-height: 78px; }}
    .metric strong {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric span {{ display: block; margin-top: 6px; font-size: 22px; font-weight: 720; }}
    .section {{ padding: 4px 0 10px; }}
    .section-header {{ margin-bottom: 10px; display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}
    .section-body {{ padding: 0; }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .learning-card {{ border: 1px solid var(--border); border-radius: 8px; padding: 14px; background: var(--panel-soft); }}
    .learning-card p {{ margin: 10px 0 0; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .chip {{ display: inline-flex; align-items: center; border: 1px solid #cbd6ea; border-radius: 999px; padding: 2px 8px; background: var(--accent-bg); color: var(--accent); font-size: 12px; margin: 2px 4px 2px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: var(--panel-soft); font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: var(--code); padding: 1px 4px; border-radius: 4px; word-break: break-word; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 7px 0; }}
    small, .muted {{ color: var(--muted); }}
    .practice {{ margin: 0; padding: 12px; border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 6px; background: var(--panel-soft); }}
    @media (max-width: 760px) {{
      .topbar-inner {{ padding: 10px 16px; align-items: flex-start; flex-direction: column; }}
      main {{ padding: 16px; }}
      header.hero {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">AgentPack</div>
    <nav aria-label="Learning dashboard sections">
      <a href="#concepts">Concepts</a>
      <a href="#files">Files</a>
      <a href="#cards">Cards</a>
      <a href="#lessons">Lessons</a>
      <a href="#practice">Practice</a>
    </nav>
  </div>
</div>
<main>
  <header class="hero">
    <div>
    <p class="eyebrow">Learning dashboard</p>
    <h1>AgentPack Learn Dashboard</h1>
    <p class="subtitle">{html.escape(report.task)}</p>
    </div>
    <div>
      <p><strong>Scope</strong><br><span class="muted">{html.escape(report.scope)}</span></p>
      <p><strong>Since</strong><br><span class="muted">{html.escape(report.since or "not specified")}</span></p>
    </div>
  </header>
  <div class="metric-grid">
    <section class="metric"><strong>Changed Files</strong><span>{len(report.source_files)}</span></section>
    <section class="metric"><strong>Concepts</strong><span>{len(report.concepts)}</span></section>
    <section class="metric"><strong>Cards</strong><span>{len(report.learning_cards)}</span></section>
    <section class="metric"><strong>Agent Lessons</strong><span>{len(report.agent_lessons)}</span></section>
  </div>
  <section id="concepts" class="section"><div class="section-header"><h2>Concepts</h2><small>Detected from changed-file evidence</small></div><div class="section-body chips">{concepts}</div></section>
  <section id="files" class="section"><div class="section-header"><h2>Changed File Evidence</h2><small>Source-backed learning inputs</small></div><div class="section-body"><div class="table-wrap"><table><thead><tr><th>Path</th><th>Change</th><th>Why</th><th>Concepts</th></tr></thead><tbody>{source_rows}</tbody></table></div></div></section>
  <section id="cards" class="section"><div class="section-header"><h2>Learning Cards</h2><small>Review-ready summaries</small></div><div class="section-body card-grid">{cards}</div></section>
  <section class="section"><div class="section-header"><h2>Risks and Tests</h2><small>What to review next</small></div><div class="section-body card-grid"><article class="learning-card"><h3>Risks</h3><ul>{risks}</ul></article><article class="learning-card"><h3>Tests</h3><ul>{tests}</ul></article></div></section>
  <section id="lessons" class="section"><div class="section-header"><h2>Agent Lessons</h2><small>Rules captured for future runs</small></div><div class="section-body"><ul>{lessons}</ul></div></section>
  <section id="practice" class="section"><div class="section-header"><h2>Next Practice</h2><small>One practical follow-up</small></div><div class="section-body"><p class="practice">{drills}</p></div></section>
</main>
</body>
</html>
"""


def _file_chips(values: list[str]) -> str:
    return "".join(f'<span class="chip">{html.escape(value)}</span>' for value in values) or '<span class="muted">none</span>'


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
