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
    ]
    if report.issue_references:
        lines.append("Issue references: " + ", ".join(report.issue_references))
    lines.extend(["", "## Changed File Evidence"])
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
    topics = "".join(
        '<article class="learning-card topic-card">'
        f"<h3>{html.escape(topic.title)}</h3>"
        f"<p>{html.escape(topic.why)}</p>"
        f'<p class="evidence"><strong>Evidence</strong><br>{_file_chips(topic.files)}</p>'
        f'<p class="evidence"><strong>Concepts</strong><br>{_file_chips(topic.concepts)}</p>'
        f'<label class="copy-label">Copy-ready study prompt</label><pre class="copy-prompt">{html.escape(topic.prompt)}</pre>'
        "</article>"
        for topic in report.learning_topics
    ) or '<p class="muted">No learning topics generated.</p>'
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
      --bg: #eef2f6;
      --glass: rgba(255, 255, 255, 0.74);
      --glass-strong: rgba(255, 255, 255, 0.88);
      --panel: rgba(255, 255, 255, 0.78);
      --panel-soft: rgba(248, 250, 252, 0.82);
      --border: rgba(137, 151, 172, 0.34);
      --text: #131820;
      --muted: #526071;
      --focus: #0f62fe;
      --accent: #2157bd;
      --accent-strong: #173f8c;
      --accent-bg: rgba(225, 235, 255, 0.9);
      --code: rgba(231, 237, 244, 0.92);
      --shadow: 0 1px 2px rgba(19, 24, 32, 0.06), 0 12px 32px rgba(19, 24, 32, 0.07);
      --shadow-soft: 0 1px 1px rgba(19, 24, 32, 0.04), 0 10px 24px rgba(19, 24, 32, 0.055);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background-color: var(--bg); background-image: linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0) 220px), linear-gradient(rgba(31, 42, 68, 0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(31, 42, 68, 0.045) 1px, transparent 1px); background-size: auto, 28px 28px, 28px 28px; color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 16px; line-height: 1.5; }}
    a:focus-visible, button:focus-visible, [tabindex]:focus-visible {{ outline: 3px solid rgba(15, 98, 254, 0.34); outline-offset: 3px; }}
    .skip-link {{ position: absolute; left: 16px; top: -48px; z-index: 4; padding: 10px 12px; border-radius: 8px; background: var(--text); color: #fff; text-decoration: none; }}
    .skip-link:focus {{ top: 12px; }}
    .topbar {{ position: sticky; top: 0; z-index: 2; background: rgba(255,255,255,0.76); border-bottom: 1px solid rgba(137,151,172,0.24); box-shadow: 0 1px 0 rgba(111,126,148,0.12); backdrop-filter: blur(18px) saturate(150%); }}
    .topbar-inner {{ max-width: 1120px; margin: 0 auto; padding: 10px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .brand {{ font-weight: 760; color: var(--accent-strong); }}
    nav {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    nav a {{ min-height: 36px; display: inline-flex; align-items: center; color: var(--muted); text-decoration: none; font-size: 13px; font-weight: 560; padding: 7px 11px; border: 1px solid transparent; border-radius: 999px; transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease; }}
    nav a:hover, nav a:focus-visible {{ background: rgba(255,255,255,0.82); border-color: var(--border); color: var(--text); }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    header.hero {{ padding: 30px 0 24px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 260px); gap: 24px; align-items: end; border-bottom: 1px solid rgba(137,151,172,0.24); }}
    h1, h2, h3 {{ line-height: 1.2; margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 34px; font-weight: 780; }}
    h2 {{ font-size: 18px; font-weight: 720; }}
    h3 {{ font-size: 15px; font-weight: 680; }}
    section {{ margin: 22px 0; }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 760; text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 8px; }}
    .subtitle {{ color: var(--muted); margin: 10px 0 0; max-width: 760px; font-size: 15px; line-height: 1.6; }}
    .meta-stack {{ display: grid; gap: 8px; }}
    .meta {{ color: var(--muted); margin: 0; padding: 12px 14px; border: 1px solid rgba(255,255,255,0.72); border-radius: 8px; background: var(--glass); box-shadow: var(--shadow-soft); backdrop-filter: blur(12px) saturate(130%); }}
    .meta strong {{ color: var(--text); }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .metric {{ background: var(--panel); border: 1px solid rgba(255,255,255,0.76); border-radius: 8px; padding: 14px; min-height: 78px; box-shadow: var(--shadow-soft); backdrop-filter: blur(14px) saturate(135%); }}
    .metric strong {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric span {{ display: block; margin-top: 6px; font-size: 22px; font-weight: 720; }}
    .section {{ padding: 6px 0 10px; }}
    .section-header {{ margin-bottom: 12px; display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}
    .section-body {{ padding: 0; }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .learning-card {{ border: 1px solid rgba(255,255,255,0.76); border-radius: 8px; padding: 14px; background: var(--panel); box-shadow: var(--shadow-soft); backdrop-filter: blur(14px) saturate(135%); }}
    .learning-card p {{ margin: 10px 0 0; }}
    .topic-card {{ display: grid; gap: 8px; }}
    .copy-label {{ color: var(--muted); font-size: 12px; font-weight: 680; text-transform: uppercase; letter-spacing: 0.04em; }}
    .copy-prompt {{ margin: 0; max-height: 240px; overflow: auto; white-space: pre-wrap; border: 1px solid var(--border); border-radius: 8px; padding: 12px; background: rgba(246,248,251,0.88); color: var(--text); font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; user-select: all; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .chip {{ display: inline-flex; align-items: center; border: 1px solid rgba(148,163,184,0.48); border-radius: 999px; padding: 2px 8px; background: var(--accent-bg); color: var(--accent); font-size: 12px; margin: 2px 4px 2px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid rgba(255,255,255,0.76); border-radius: 8px; background: var(--glass-strong); box-shadow: var(--shadow-soft); backdrop-filter: blur(14px) saturate(135%); }}
    th, td {{ border-bottom: 1px solid rgba(137,151,172,0.24); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background: rgba(248,250,252,0.94); font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: var(--code); padding: 1px 4px; border-radius: 4px; word-break: break-word; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 7px 0; }}
    small, .muted {{ color: var(--muted); }}
    .practice {{ margin: 0; padding: 12px 14px; border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 8px; background: var(--glass); color: var(--muted); backdrop-filter: blur(12px) saturate(125%); }}
    @media (prefers-reduced-motion: reduce) {{
      html {{ scroll-behavior: auto; }}
      nav a {{ transition: none; }}
    }}
    @supports not ((backdrop-filter: blur(1px))) {{
      .topbar, .meta, .metric, .learning-card, .practice, .table-wrap {{ background: #ffffff; }}
    }}
    @media (max-width: 760px) {{
      .topbar-inner {{ padding: 10px 16px; align-items: flex-start; flex-direction: column; }}
      main {{ padding: 16px; }}
      header.hero {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
<a class="skip-link" href="#main">Skip to learning dashboard</a>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">AgentPack</div>
    <nav aria-label="Learning dashboard sections">
      <a href="#concepts">Concepts</a>
      <a href="#files">Files</a>
      <a href="#topics">Topics</a>
      <a href="#cards">Cards</a>
      <a href="#lessons">Lessons</a>
      <a href="#practice">Practice</a>
    </nav>
  </div>
</div>
<main id="main">
  <header class="hero">
    <div>
    <p class="eyebrow">Learning dashboard</p>
    <h1>AgentPack Learn Dashboard</h1>
    <p class="subtitle">{html.escape(report.task)}</p>
    </div>
    <div class="meta-stack">
      <p class="meta"><strong>Scope</strong><br><span class="muted">{html.escape(report.scope)}</span></p>
      <p class="meta"><strong>Since</strong><br><span class="muted">{html.escape(report.since or "not specified")}</span></p>
    </div>
  </header>
  <div class="metric-grid">
    <section class="metric"><strong>Changed Files</strong><span>{len(report.source_files)}</span></section>
    <section class="metric"><strong>Concepts</strong><span>{len(report.concepts)}</span></section>
    <section class="metric"><strong>Learning Topics</strong><span>{len(report.learning_topics)}</span></section>
    <section class="metric"><strong>Cards</strong><span>{len(report.learning_cards)}</span></section>
    <section class="metric"><strong>Agent Lessons</strong><span>{len(report.agent_lessons)}</span></section>
  </div>
  <section id="concepts" class="section"><div class="section-header"><h2>Concepts</h2><small>Detected from changed-file evidence</small></div><div class="section-body chips">{concepts}</div></section>
  <section id="files" class="section"><div class="section-header"><h2>Changed File Evidence</h2><small>Source-backed learning inputs</small></div><div class="section-body"><div class="table-wrap"><table><thead><tr><th>Path</th><th>Change</th><th>Why</th><th>Concepts</th></tr></thead><tbody>{source_rows}</tbody></table></div></div></section>
  <section id="topics" class="section"><div class="section-header"><h2>Learning Topics</h2><small>Copy a source-backed prompt into GPT, Gemini, or another study tool</small></div><div class="section-body card-grid">{topics}</div></section>
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
    if report.issue_references:
        lines.append("**Issue references:** " + ", ".join(report.issue_references))
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
    lines.extend(["", "## Learning Topics"])
    for topic in report.learning_topics:
        lines.append(f"### {topic.title}")
        lines.append(topic.why)
        if topic.files:
            lines.append("Evidence: " + ", ".join(f"`{path}`" for path in topic.files))
        if topic.concepts:
            lines.append("Concepts: " + ", ".join(topic.concepts))
        lines.extend(["", "Copy-ready study prompt:", "```text", topic.prompt, "```", ""])
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
