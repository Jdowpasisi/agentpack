from __future__ import annotations

import typer
from rich.table import Table

from agentpack.commands._shared import _root, console
from agentpack.core.config import load_config
from agentpack.router.discovery import discover_inventory, write_inventory_index

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
    inventory = discover_inventory(root, cfg.skills.paths)
    path = write_inventory_index(root, inventory)
    console.print(
        f"Indexed {len(inventory.skills)} skills and {len(inventory.rules)} rules at {path}"
    )
