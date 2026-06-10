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
    skills_inventory = _skills_inventory_panel(snapshot)
    learning = _learning_rows(snapshot)
    benchmarks = _benchmark_rows(snapshot)
    misses = _miss_rows(snapshot)
    actions = _action_rows(snapshot)
    loop = _loop_panel(snapshot)
    status_class = _status_class(snapshot.context.status)
    task_text = snapshot.task.text or "No task found"
    generated_at = snapshot.generated_at or snapshot.context.generated_at or "unknown"
    git_label = " ".join(part for part in [snapshot.project.branch or "unknown", snapshot.project.git_sha] if part).strip()

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentPack Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef2f6;
      --glass: rgba(255, 255, 255, 0.74);
      --glass-strong: rgba(255, 255, 255, 0.88);
      --panel: rgba(255, 255, 255, 0.78);
      --panel-soft: rgba(248, 250, 252, 0.82);
      --border: rgba(137, 151, 172, 0.34);
      --border-strong: rgba(111, 126, 148, 0.48);
      --text: #131820;
      --muted: #526071;
      --subtle: #768293;
      --good: #137047;
      --good-bg: rgba(222, 245, 231, 0.9);
      --warn: #8a6100;
      --warn-bg: rgba(255, 242, 202, 0.92);
      --bad: #b4232c;
      --bad-bg: rgba(255, 232, 232, 0.92);
      --accent: #2157bd;
      --accent-strong: #173f8c;
      --accent-bg: rgba(225, 235, 255, 0.9);
      --code: rgba(231, 237, 244, 0.92);
      --shadow: 0 1px 2px rgba(19, 24, 32, 0.06), 0 12px 32px rgba(19, 24, 32, 0.07);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background-color: var(--bg); background-image: linear-gradient(rgba(31, 42, 68, 0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(31, 42, 68, 0.045) 1px, transparent 1px); background-size: 28px 28px; color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
    .topbar {{ position: sticky; top: 0; z-index: 2; background: var(--glass); border-bottom: 1px solid rgba(255,255,255,0.68); box-shadow: 0 1px 0 rgba(111,126,148,0.16); backdrop-filter: blur(16px) saturate(145%); }}
    .topbar-inner {{ max-width: 1240px; margin: 0 auto; padding: 10px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .brand {{ font-weight: 760; letter-spacing: 0; color: var(--accent-strong); }}
    nav {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    nav a {{ color: var(--muted); text-decoration: none; font-size: 13px; padding: 5px 9px; border: 1px solid transparent; border-radius: 999px; }}
    nav a:hover, nav a:focus-visible {{ background: rgba(255,255,255,0.72); border-color: var(--border); color: var(--text); outline: none; }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 24px; }}
    header.hero {{ padding: 28px 0 22px; display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: end; border-bottom: 1px solid rgba(137,151,172,0.24); }}
    h1, h2, h3 {{ line-height: 1.2; margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 34px; font-weight: 780; }}
    h2 {{ font-size: 18px; font-weight: 720; }}
    h3 {{ font-size: 15px; font-weight: 680; }}
    section {{ margin: 20px 0; }}
    .section {{ padding: 6px 0 10px; }}
    .section-header {{ margin-bottom: 10px; display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}
    .section-body {{ padding: 0; }}
    .section-body > h3 {{ margin: 18px 0 8px; color: var(--text); }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 760; text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 8px; }}
    .subtitle {{ color: var(--muted); margin: 10px 0 0; max-width: 760px; font-size: 15px; }}
    .meta-stack {{ display: grid; gap: 8px; }}
    .meta {{ color: var(--muted); margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--glass); box-shadow: 0 1px 1px rgba(19,24,32,0.03); backdrop-filter: blur(12px) saturate(130%); }}
    .meta strong {{ color: var(--text); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 10px; }}
    .metric {{ background: var(--panel); border: 1px solid rgba(255,255,255,0.72); border-radius: 8px; padding: 14px; min-height: 78px; box-shadow: var(--shadow); backdrop-filter: blur(14px) saturate(135%); }}
    .metric strong {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric span {{ display: block; margin-top: 6px; font-size: 22px; font-weight: 720; }}
    .metric.compact span {{ font-size: 17px; }}
    .callout {{ margin-top: 12px; padding: 10px 12px; border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 8px; background: var(--glass); color: var(--muted); backdrop-filter: blur(12px) saturate(125%); }}
    table {{ width: 100%; border-collapse: collapse; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid rgba(255,255,255,0.76); border-radius: 8px; background: var(--glass-strong); box-shadow: var(--shadow); backdrop-filter: blur(14px) saturate(135%); }}
    th, td {{ border-bottom: 1px solid rgba(137,151,172,0.24); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: rgba(248,250,252,0.9); font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; position: sticky; top: 43px; z-index: 1; }}
    tr:last-child td {{ border-bottom: 0; }}
    tbody tr:hover {{ background: rgba(234,240,255,0.38); }}
    code {{ background: var(--code); padding: 1px 4px; border-radius: 4px; word-break: break-word; }}
    ul {{ padding-left: 18px; margin: 0; }}
    li {{ margin: 7px 0; }}
    small {{ color: var(--muted); }}
    .pill {{ display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; background: rgba(255,255,255,0.64); color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .fresh, .used_helpful {{ color: var(--good); }}
    .stale, .ignored, .used_noisy {{ color: var(--warn); }}
    .missing, .bad_recommendation {{ color: var(--bad); }}
    .unknown, .recommended_only, .none {{ color: var(--muted); }}
    .pill.fresh, .pill.used_helpful {{ border-color: #b7e2c7; background: var(--good-bg); color: var(--good); }}
    .pill.stale, .pill.ignored, .pill.used_noisy {{ border-color: #f2d28c; background: var(--warn-bg); color: var(--warn); }}
    .pill.missing, .pill.bad_recommendation {{ border-color: #f0b7b7; background: var(--bad-bg); color: var(--bad); }}
    .path-col {{ min-width: 220px; }}
    .reason-col {{ min-width: 260px; }}
    .two-col {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 0.45fr); gap: 18px; align-items: start; }}
    .action-list {{ display: grid; gap: 10px; padding: 0; list-style: none; }}
    .action-list li {{ margin: 0; padding: 12px; border: 1px solid rgba(255,255,255,0.72); border-radius: 8px; background: var(--panel); box-shadow: var(--shadow); backdrop-filter: blur(14px) saturate(135%); }}
    @supports not ((backdrop-filter: blur(1px))) {{
      .topbar, .meta, .metric, .callout, .table-wrap, .action-list li {{ background: #ffffff; }}
    }}
    @media (max-width: 760px) {{
      .topbar-inner {{ padding: 10px 16px; align-items: flex-start; flex-direction: column; }}
      main {{ padding: 16px; }}
      header.hero, .two-col {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">AgentPack</div>
    <nav aria-label="Dashboard sections">
      <a href="#health">Health</a>
      <a href="#files">Files</a>
      <a href="#skills">Skills</a>
      <a href="#inventory">Inventory</a>
      <a href="#learning">Learning</a>
      <a href="#benchmarks">Benchmarks</a>
      <a href="#loop">Loop</a>
      <a href="#actions">Actions</a>
    </nav>
  </div>
</div>
<main>
  <header class="hero">
    <div>
    <p class="eyebrow">Local control plane</p>
    <h1>AgentPack Dashboard</h1>
    <p class="subtitle">{_e(task_text)}</p>
    </div>
    <div class="meta-stack">
      <p class="meta"><strong>Project</strong><br>{_e(snapshot.project.name)}<br><small>{_e(snapshot.project.path)}</small></p>
      <p class="meta"><strong>Git</strong><br>{_e(git_label or "unknown")}</p>
      <p class="meta"><strong>Generated</strong><br>{_e(generated_at)}</p>
    </div>
  </header>

  <section id="health" class="section">
    <div class="section-header"><h2>Context Health</h2><span class="pill {status_class}">{_e(snapshot.context.status)}</span></div>
    <div class="section-body">
      <div class="grid">
      <div class="metric"><strong>Mode</strong><span>{_e(snapshot.context.mode or "unknown")}</span></div>
      <div class="metric"><strong>Packed Tokens</strong><span>{snapshot.context.packed_tokens:,}</span></div>
      <div class="metric"><strong>Raw Tokens</strong><span>{snapshot.context.raw_tokens:,}</span></div>
      <div class="metric"><strong>Savings</strong><span>{snapshot.context.saving_pct:.1f}%</span></div>
      <div class="metric"><strong>Selected Files</strong><span>{snapshot.context.selected_files_count}</span></div>
      <div class="metric"><strong>Threads</strong><span>{snapshot.threads.active_count}</span></div>
    </div>
    {_stale_reason(snapshot)}
    </div>
  </section>

  <section id="files" class="section">
    <div class="section-header"><h2>Selected Files</h2><small>Top {min(len(snapshot.selected_files), MAX_RENDERED_FILES)} files from the active context pack</small></div>
    <div class="section-body"><div class="table-wrap"><table><thead><tr><th class="path-col">Path</th><th>Mode</th><th>Score</th><th>Tokens</th><th class="reason-col">Reasons</th></tr></thead><tbody>{files}</tbody></table></div></div>
  </section>

  <section id="skills" class="section">
    <div class="section-header"><h2>Skills</h2><small>Task-specific and baseline recommendations</small></div>
    <div class="section-body"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Confidence</th><th>Score</th><th>Status</th><th>Side Effect</th><th class="reason-col">Reasons</th></tr></thead><tbody>{skills}</tbody></table></div></div>
  </section>

  {skills_inventory}

  <section id="learning" class="section">
    <div class="section-header"><h2>Learning</h2><small>Artifacts that can improve future routing and handoffs</small></div>
    <div class="section-body"><ul>{learning}</ul></div>
  </section>

  <section id="benchmarks" class="section">
    <div class="section-header"><h2>Benchmarks</h2><small>Recent routing quality signals</small></div>
    <div class="section-body two-col">
      <div><h3>Metrics</h3><div class="table-wrap"><table><thead><tr><th>Metric</th><th>Recent Average</th></tr></thead><tbody>{benchmarks}</tbody></table></div></div>
      <div><h3>Recent Misses</h3><div class="table-wrap"><table><thead><tr><th>Expected File</th><th>Reason</th></tr></thead><tbody>{misses}</tbody></table></div></div>
    </div>
  </section>

  {loop}

  <section id="actions" class="section">
    <div class="section-header"><h2>Suggested Actions</h2><small>Next commands based on local state</small></div>
    <div class="section-body"><ul class="action-list">{actions}</ul></div>
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


def _skills_inventory_panel(snapshot: DashboardSnapshot) -> str:
    inventory = snapshot.skills_inventory
    if not inventory.available:
        reason = inventory.index_error or "No skills index available."
        return f"""
  <section id="inventory" class="section">
    <div class="section-header"><h2>Skills Inventory</h2><small>Local skill discovery</small></div>
    <div class="section-body"><p>{_e(reason)}</p></div>
  </section>"""

    domains = "".join(
        f"<li>{_e(item.name)}: {item.count}</li>"
        for item in inventory.domains[:20]
    ) or "<li>No domains found.</li>"
    sources = "".join(
        "<tr>"
        f"<td><code>{_e(item.configured_path)}</code></td>"
        f"<td>{_e(item.resolved_path)}</td>"
        f"<td>{'yes' if item.exists else 'no'}</td>"
        f"<td>{item.file_count}</td>"
        "</tr>"
        for item in inventory.sources
    ) or '<tr><td colspan="4">No configured skill sources found.</td></tr>'
    rows = "".join(
        "<tr>"
        f"<td>{_e(item.name)}</td>"
        f"<td>{_e(', '.join(item.domains))}</td>"
        f"<td>{_e(item.source)}</td>"
        f"<td><code>{_e(item.path)}</code></td>"
        f"<td>{_e(item.side_effect_level or 'unknown')}</td>"
        f"<td>{_metadata_cell(item.metadata_quality, item.metadata)}</td>"
        "</tr>"
        for item in inventory.rows
    ) or '<tr><td colspan="6">No skills discovered.</td></tr>'
    duplicate_names = ", ".join(inventory.duplicate_names) or "none"
    return f"""
  <section id="inventory" class="section">
    <div class="section-header"><h2>Skills Inventory</h2><small>Directories, domains, and metadata quality</small></div>
    <div class="section-body">
      <div class="grid">
      <div class="metric"><strong>Skills</strong><span>{inventory.total_skills}</span></div>
      <div class="metric"><strong>Rules</strong><span>{inventory.total_rules}</span></div>
      <div class="metric"><strong>Uncategorized</strong><span>{inventory.uncategorized_count}</span></div>
      <div class="metric"><strong>Inferred Metadata</strong><span>{inventory.missing_metadata_count}</span></div>
    </div>
    <p class="callout"><small>Index: {_e(inventory.index_reason or "unknown")}; refreshed: {'yes' if inventory.index_refreshed else 'no'}; duplicate names: {_e(duplicate_names)}</small></p>
    <h3>Domains</h3>
    <ul>{domains}</ul>
    <h3>Directories</h3>
    <div class="table-wrap"><table><thead><tr><th>Configured</th><th>Resolved</th><th>Exists</th><th>Files</th></tr></thead><tbody>{sources}</tbody></table></div>
    <h3>Discovered Skills</h3>
    <div class="table-wrap"><table><thead><tr><th>Skill</th><th>Domain</th><th>Source</th><th>Path</th><th>Side Effect</th><th>Metadata</th></tr></thead><tbody>{rows}</tbody></table></div>
    </div>
  </section>"""


def _metadata_cell(quality: str, metadata: list[str]) -> str:
    details = "".join(f"<li>{_e(item)}</li>" for item in metadata)
    body = f"<ul>{details}</ul>" if details else "<small>No metadata detected.</small>"
    return f'<span class="pill">{_e(quality)}</span>{body}'


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


def _loop_panel(snapshot: DashboardSnapshot) -> str:
    if not snapshot.loop.exists:
        return """
  <section id="loop" class="section">
    <div class="section-header"><h2>Ralph Loop</h2><small>Improvement loop state</small></div>
    <div class="section-body"><p>No Ralph Loop state found.</p></div>
  </section>"""
    return f"""
  <section id="loop" class="section">
    <div class="section-header"><h2>Ralph Loop</h2><small>Improvement loop state</small></div>
    <div class="section-body">
      <div class="grid">
      <div class="metric"><strong>Status</strong><span>{_e(snapshot.loop.status)}</span></div>
      <div class="metric"><strong>Iteration</strong><span>{snapshot.loop.iteration}/{snapshot.loop.max_iterations}</span></div>
      <div class="metric"><strong>Runner</strong><span>{_e(snapshot.loop.last_runner_status or "not run")}</span></div>
      <div class="metric"><strong>Verification</strong><span>{_e(snapshot.loop.last_verification_status or "not run")}</span></div>
    </div>
    <p><strong>Task:</strong> {_e(snapshot.loop.task)}</p>
    <p><strong>Blocked reason:</strong> {_e(snapshot.loop.blocked_reason or "none")}</p>
    <p><strong>Next:</strong> <code>{_e(snapshot.loop.next_action)}</code></p>
    </div>
  </section>"""


def _stale_reason(snapshot: DashboardSnapshot) -> str:
    if not snapshot.context.stale_reason:
        return ""
    return f'<p class="callout"><small>{_e(snapshot.context.stale_reason)}</small></p>'


def _status_class(value: object) -> str:
    text = str(value)
    return text if text in {"fresh", "stale", "missing", "unknown"} else "unknown"


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
