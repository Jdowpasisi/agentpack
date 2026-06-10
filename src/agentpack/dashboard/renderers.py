from __future__ import annotations

import html
from collections.abc import Iterable

from agentpack.dashboard.models import DashboardSnapshot, SkillRow


MAX_RENDERED_FILES = 50
MAX_RENDERED_MISSES = 20


def render_dashboard_html(snapshot: DashboardSnapshot) -> str:
    files = _selected_file_rows(snapshot)
    skills = _skill_rows(snapshot.skills.task_specific, "task-specific") + _skill_rows(snapshot.skills.baseline, "baseline")
    if not skills:
        skills = '<tr><td colspan="7">No skill recommendations found.</td></tr>'
    learning = _learning_rows(snapshot)
    benchmarks = _benchmark_rows(snapshot)
    misses = _miss_rows(snapshot)
    actions = _action_rows(snapshot)
    status_class = _status_class(snapshot.context.status)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentPack Dashboard</title>
  <style>
    :root {{ color-scheme: light; --bg: #f6f8fa; --panel: #ffffff; --border: #d0d7de; --text: #1f2328; --muted: #57606a; --good: #1a7f37; --warn: #9a6700; --bad: #cf222e; --accent: #0969da; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ padding: 20px 0 24px; border-bottom: 1px solid var(--border); }}
    h1, h2, h3 {{ line-height: 1.2; margin: 0 0 10px; }}
    section {{ margin: 24px 0; }}
    .meta {{ color: var(--muted); margin: 4px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px; min-height: 78px; }}
    .metric strong {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric span {{ display: block; margin-top: 6px; font-size: 22px; font-weight: 650; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f3f6; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef1f4; padding: 1px 4px; border-radius: 4px; word-break: break-word; }}
    ul {{ padding-left: 20px; }}
    li {{ margin: 8px 0; }}
    small {{ color: var(--muted); }}
    .pill {{ display: inline-block; border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; background: #f6f8fa; font-size: 12px; }}
    .fresh, .used_helpful {{ color: var(--good); }}
    .stale, .ignored, .used_noisy {{ color: var(--warn); }}
    .missing, .bad_recommendation {{ color: var(--bad); }}
    .unknown, .recommended_only, .none {{ color: var(--muted); }}
    @media (max-width: 760px) {{
      main {{ padding: 16px; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>AgentPack Dashboard</h1>
    <p class="meta"><strong>Project:</strong> {_e(snapshot.project.name)} <small>{_e(snapshot.project.path)}</small></p>
    <p class="meta"><strong>Task:</strong> {_e(snapshot.task.text or "No task found")}</p>
    <p class="meta"><strong>Git:</strong> {_e(snapshot.project.branch or "unknown")} {_e(snapshot.project.git_sha or "")}</p>
    <p class="meta"><strong>Generated:</strong> {_e(snapshot.generated_at or "unknown")}</p>
  </header>

  <section>
    <h2>Context Health</h2>
    <div class="grid">
      <div class="metric"><strong>Status</strong><span class="{status_class}">{_e(snapshot.context.status)}</span></div>
      <div class="metric"><strong>Mode</strong><span>{_e(snapshot.context.mode or "unknown")}</span></div>
      <div class="metric"><strong>Packed Tokens</strong><span>{snapshot.context.packed_tokens:,}</span></div>
      <div class="metric"><strong>Raw Tokens</strong><span>{snapshot.context.raw_tokens:,}</span></div>
      <div class="metric"><strong>Savings</strong><span>{snapshot.context.saving_pct:.1f}%</span></div>
      <div class="metric"><strong>Selected Files</strong><span>{snapshot.context.selected_files_count}</span></div>
      <div class="metric"><strong>Threads</strong><span>{snapshot.threads.active_count}</span></div>
    </div>
    {_stale_reason(snapshot)}
  </section>

  <section>
    <h2>Selected Files</h2>
    <table><thead><tr><th>Path</th><th>Mode</th><th>Score</th><th>Tokens</th><th>Reasons</th></tr></thead><tbody>{files}</tbody></table>
  </section>

  <section>
    <h2>Skills</h2>
    <table><thead><tr><th>Name</th><th>Type</th><th>Confidence</th><th>Score</th><th>Status</th><th>Side Effect</th><th>Reasons</th></tr></thead><tbody>{skills}</tbody></table>
  </section>

  <section>
    <h2>Learning</h2>
    <ul>{learning}</ul>
  </section>

  <section>
    <h2>Benchmarks</h2>
    <table><thead><tr><th>Metric</th><th>Recent Average</th></tr></thead><tbody>{benchmarks}</tbody></table>
    <h3>Recent Misses</h3>
    <table><thead><tr><th>Expected File</th><th>Reason</th></tr></thead><tbody>{misses}</tbody></table>
  </section>

  <section>
    <h2>Suggested Actions</h2>
    <ul>{actions}</ul>
  </section>
</main>
</body>
</html>
"""


def _selected_file_rows(snapshot: DashboardSnapshot) -> str:
    rows = "".join(
        "<tr>"
        f"<td><code>{_e(item.path)}</code></td>"
        f"<td>{_e(item.include_mode)}</td>"
        f"<td>{item.score:.1f}</td>"
        f"<td>{item.tokens}</td>"
        f"<td>{_e(', '.join(item.reasons[:3]))}</td>"
        "</tr>"
        for item in snapshot.selected_files[:MAX_RENDERED_FILES]
    )
    return rows or '<tr><td colspan="5">No selected files found.</td></tr>'


def _skill_rows(items: Iterable[SkillRow], kind: str) -> str:
    return "".join(
        "<tr>"
        f"<td>{_e(item.name)}</td>"
        f"<td>{_e(kind)}</td>"
        f"<td>{item.confidence:.2f}</td>"
        f"<td>{item.score:.1f}</td>"
        f'<td><span class="pill {item.status}">{_e(item.status)}</span></td>'
        f"<td>{_e(item.side_effect_level or 'unknown')}</td>"
        f"<td>{_e(', '.join(item.reasons[:3]))}</td>"
        "</tr>"
        for item in items
    )


def _learning_rows(snapshot: DashboardSnapshot) -> str:
    rows = []
    for item in snapshot.learning:
        state = "present" if item.exists else "missing"
        excerpt = f"<br><small>{_e(item.excerpt)}</small>" if item.excerpt else ""
        rows.append(f"<li>{_e(item.label)}: <code>{_e(item.path)}</code> <span class=\"pill\">{state}</span>{excerpt}</li>")
    return "".join(rows) or "<li>No learning artifacts checked.</li>"


def _benchmark_rows(snapshot: DashboardSnapshot) -> str:
    rows = "".join(
        f"<tr><td><code>{_e(key)}</code></td><td>{value:.3f}</td></tr>"
        for key, value in sorted(snapshot.benchmarks.averages.items())
    )
    return rows or '<tr><td colspan="2">No benchmark metrics found.</td></tr>'


def _miss_rows(snapshot: DashboardSnapshot) -> str:
    rows = []
    for miss in snapshot.benchmarks.misses[:MAX_RENDERED_MISSES]:
        path = miss.get("path") or miss.get("file") or miss.get("expected_file") or ""
        reason = miss.get("reason") or miss.get("status") or miss.get("remediation") or ""
        rows.append(f"<tr><td><code>{_e(path)}</code></td><td>{_e(reason)}</td></tr>")
    return "".join(rows) or '<tr><td colspan="2">No recent benchmark misses.</td></tr>'


def _action_rows(snapshot: DashboardSnapshot) -> str:
    rows = [
        f"<li><strong>{_e(item.label)}</strong><br><code>{_e(item.command)}</code><br><small>{_e(item.reason)}</small></li>"
        for item in snapshot.suggested_actions
    ]
    return "".join(rows) or "<li>No suggested actions.</li>"


def _stale_reason(snapshot: DashboardSnapshot) -> str:
    if not snapshot.context.stale_reason:
        return ""
    return f'<p><small>{_e(snapshot.context.stale_reason)}</small></p>'


def _status_class(value: object) -> str:
    text = str(value)
    return text if text in {"fresh", "stale", "missing", "unknown"} else "unknown"


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
