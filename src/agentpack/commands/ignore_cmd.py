from __future__ import annotations

import typer

from agentpack.commands._shared import console, _root
from agentpack.core.ignore import agentignore_sync_status, format_import_summary


def register(app: typer.Typer) -> None:
    ignore_app = typer.Typer(help="Inspect and sync AgentPack ignore rules.")

    @ignore_app.command("sync")
    def sync(
        dry_run: bool = typer.Option(False, "--dry-run", help="Show the planned .agentignore update without writing."),
        check: bool = typer.Option(False, "--check", help="Exit non-zero when .agentignore is stale."),
    ) -> None:
        """Sync imported generated/noisy rules into .agentignore."""
        root = _root()
        status = agentignore_sync_status(root)

        if dry_run:
            console.print(f"[bold]Action:[/] {status.action}")
            if status.imported_rules:
                console.print(f"[dim]{format_import_summary(status)}[/]")
            else:
                console.print("[dim]Imported 0 generated/noisy rules.[/]")
            raise typer.Exit(0)

        if check:
            if status.action == "unchanged":
                console.print("[green].agentignore is in sync.[/]")
                raise typer.Exit(0)
            console.print("[yellow].agentignore is stale; run `agentpack ignore sync`.[/]")
            raise typer.Exit(1)

        previous_action = status.action
        if previous_action != "unchanged":
            status.path.parent.mkdir(parents=True, exist_ok=True)
            status.path.write_text(status.desired_content, encoding="utf-8")
            status = agentignore_sync_status(root)

        if previous_action == "create":
            console.print("[green]Created .agentignore.[/]")
        elif previous_action == "update":
            console.print("[green]Updated .agentignore.[/]")
        else:
            console.print("[green].agentignore already in sync.[/]")
        if status.imported_rules:
            console.print(f"[dim]{format_import_summary(status)}[/]")

    app.add_typer(ignore_app, name="ignore")
