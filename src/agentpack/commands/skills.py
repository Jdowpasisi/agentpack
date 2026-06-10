from __future__ import annotations

import json
from datetime import datetime, timezone

import typer
from rich.table import Table

from agentpack.commands._shared import _root, console
from agentpack.core.config import load_config
from agentpack.router.prompt_builder import render_plain
from agentpack.router.discovery import discover_inventory
from agentpack.router.skills_index import ensure_inventory_index
from agentpack.router.service import RouteService

skills_app = typer.Typer(help="Inspect and index local agent skills and rules.")


def register(app: typer.Typer) -> None:
    app.add_typer(skills_app, name="skills")


@skills_app.command("scan")
def scan_skills() -> None:
    """Print discovered skills and rules without writing an index."""
    root = _root()
    cfg = load_config(root)
    inventory = discover_inventory(root, cfg.skills.paths)
    console.print(f"Found {len(inventory.skills)} skills and {len(inventory.rules)} rules")

    table = Table(show_header=True)
    table.add_column("type")
    table.add_column("name")
    table.add_column("source")
    table.add_column("description")
    for skill in inventory.skills:
        table.add_row("skill", skill.name, skill.path, skill.description[:80])
    for rule in inventory.rules:
        table.add_row("rule", rule.name, rule.path, rule.description[:80])
    console.print(table)


@skills_app.command("index")
def index_skills() -> None:
    """Write .agentpack/skills_index.json."""
    root = _root()
    cfg = load_config(root)
    result = ensure_inventory_index(root, cfg.skills.paths, force=True)
    inventory = result.document.inventory
    console.print(
        f"Indexed {len(inventory.skills)} skills and {len(inventory.rules)} rules at {result.path}"
    )


@skills_app.command("recommend")
def recommend_skills(
    task: str = typer.Option(..., "--task", help="Developer task to route."),
    explain: bool = typer.Option(False, "--explain", help="Include route files, rules, commands, and reasons."),
) -> None:
    """Recommend skills for a task."""
    try:
        result = RouteService().route_task(_root(), task)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if explain:
        console.print(render_plain(result))
        return

    table = Table(title="Recommended skills", show_header=True)
    table.add_column("skill")
    table.add_column("confidence")
    table.add_column("next")
    for item in result.selected_skills:
        table.add_row(
            item.skill.name,
            f"{item.confidence:.2f}",
            f"Load {item.skill.path}",
        )
    if not result.selected_skills:
        table.add_row("none", "-", "-")
    console.print(table)


@skills_app.command("feedback")
def record_skill_feedback(
    task: str = typer.Option(..., "--task", help="Task the skills were recommended for."),
    used_skill: list[str] = typer.Option([], "--used-skill", help="Skill name/path actually used. Repeatable."),
    changed_file: list[str] = typer.Option([], "--changed-file", help="File changed during the task. Repeatable."),
    tests_passed: bool | None = typer.Option(None, "--tests-passed/--tests-failed", help="Whether verification passed."),
    user_feedback: str = typer.Option("", "--user-feedback", help="Optional label: helpful|ignored|noisy|bad."),
) -> None:
    """Record local skill recommendation outcome feedback."""
    root = _root()
    out = root / ".agentpack" / "skill_feedback.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": task.strip(),
        "used_skills": [item.strip() for item in used_skill if item.strip()],
        "changed_files": [item.strip() for item in changed_file if item.strip()],
        "tests_passed": tests_passed,
        "user_feedback": user_feedback.strip(),
    }
    out.open("a", encoding="utf-8").write(json.dumps(record) + "\n")
    console.print(f"[green]✓[/] Recorded skill feedback in [bold]{out}[/]")
