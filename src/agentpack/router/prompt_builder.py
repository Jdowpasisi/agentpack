from __future__ import annotations

from agentpack.router.models import RouteResult


def build_agent_prompt(result: RouteResult) -> str:
    lines = [
        "Use Agentpack route result before editing.",
        "",
        f"Task: {result.task}",
        "",
        "Read these files first:",
    ]
    if result.selected_files:
        lines.extend(f"- {item['path']}" for item in result.selected_files[:10])
    else:
        lines.append("- No files selected.")

    if result.applied_rules:
        lines += ["", "Apply these rules:"]
        lines.extend(f"- {item.rule.name} ({item.rule.path})" for item in result.applied_rules)

    if result.selected_skills:
        lines += ["", "Use these skills if available:"]
        lines.extend(f"- {item.skill.name} ({item.skill.path})" for item in result.selected_skills)

    if result.safety_warnings:
        lines += ["", "Safety warnings:"]
        lines.extend(f"- {warning}" for warning in result.safety_warnings)

    if result.suggested_commands:
        lines += ["", "Consider these commands; do not run blindly:"]
        lines.extend(f"- {item.command}" for item in result.suggested_commands)

    return "\n".join(lines)


def render_plain(result: RouteResult) -> str:
    lines = [
        "Task:",
        result.task,
        "",
        "Relevant files:",
    ]
    if result.selected_files:
        for item in result.selected_files:
            why = ", ".join(item.get("reasons", [])[:2])
            suffix = f" — {why}" if why else ""
            lines.append(f"- {item['path']} ({item.get('include_mode', 'unknown')}){suffix}")
    else:
        lines.append("- none")

    lines += ["", "Applied rules:"]
    if result.applied_rules:
        for item in result.applied_rules:
            reason = "; ".join(item.reasons)
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- {item.rule.name} ({item.rule.path}){suffix}")
    else:
        lines.append("- none")

    lines += ["", "Recommended skills:"]
    if result.selected_skills:
        for item in result.selected_skills:
            reason = "; ".join(item.reasons[:2])
            suffix = f" — {reason}" if reason else ""
            lines.append(
                f"- {item.skill.name} ({item.skill.side_effect_level}, score {item.score:.0f}){suffix}"
            )
    else:
        lines.append("- none")

    lines += ["", "Suggested commands:"]
    if result.suggested_commands:
        for item in result.suggested_commands:
            lines.append(f"- {item.command} — {item.reason}")
    else:
        lines.append("- none")

    lines += ["", "Safety:"]
    if result.safety_warnings:
        lines.extend(f"- {warning}" for warning in result.safety_warnings)
    else:
        lines.append("- No external side-effect skills selected.")

    lines += ["", "Agent prompt:", result.agent_prompt]
    return "\n".join(lines)
