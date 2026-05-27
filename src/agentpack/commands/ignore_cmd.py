from __future__ import annotations

import json

import typer

from agentpack.commands._shared import console, _root
from agentpack.core.config import load_config
from agentpack.core.ignore import agentignore_sync_status, format_import_summary, load_spec
from agentpack.core.scanner import scan


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

    @ignore_app.command("suggest")
    def suggest(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Suggest generated/noisy paths that may belong in .agentignore."""
        root = _root()
        suggestions = _ignore_suggestions(root)
        if json_output:
            typer.echo(json.dumps({"suggestions": suggestions}, indent=2, sort_keys=True))
            return
        if not suggestions:
            console.print("[green]No ignore suggestions found.[/]")
            return
        for item in suggestions:
            console.print(f"[bold]{item['pattern']}[/]  [dim]{item['reason']}[/]")

    @ignore_app.command("apply")
    def apply(
        yes: bool = typer.Option(False, "--yes", help="Write suggestions to .agentignore."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Apply current ignore suggestions, or print a dry-run without --yes."""
        root = _root()
        suggestions = _ignore_suggestions(root)
        path = root / ".agentignore"
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        existing_set = {line.strip() for line in existing if line.strip() and not line.strip().startswith("#")}
        additions = [item["pattern"] for item in suggestions if item["pattern"] not in existing_set]
        if yes and additions:
            path.parent.mkdir(parents=True, exist_ok=True)
            prefix = path.read_text(encoding="utf-8").rstrip() + "\n" if path.exists() else ""
            block = "\n# AgentPack suggested noisy/generated paths\n" + "\n".join(additions) + "\n"
            path.write_text(prefix + block, encoding="utf-8")
        payload = {"applied": bool(yes), "additions": additions}
        if json_output:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
            return
        if yes:
            console.print(f"[green]✓[/] Added {len(additions)} pattern(s) to .agentignore.")
        else:
            console.print(f"[yellow]Dry run:[/] would add {len(additions)} pattern(s).")
            if additions:
                console.print("Run [bold]agentpack ignore apply --yes[/] to write them.")
        for pattern in additions[:20]:
            console.print(f"  {pattern}")

    app.add_typer(ignore_app, name="ignore")


def _ignore_suggestions(root) -> list[dict[str, str]]:
    cfg = load_config(root)
    status = agentignore_sync_status(root)
    existing = set(status.current_content.splitlines()) if status.current_content else set()
    scan_result = scan(root, load_spec(root / cfg.project.ignore_file), cfg.context.max_file_tokens)
    candidates: dict[str, str] = {}
    generated_names = {"dist", "build", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
    for fi in scan_result.all_files:
        parts = fi.path.replace("\\", "/").split("/")
        for part in parts[:-1]:
            if part in generated_names:
                candidates[f"{part}/"] = "generated/cache directory present in repo scan"
        if fi.estimated_tokens >= cfg.context.max_file_tokens * 2 and not fi.path.endswith((".md", ".py", ".ts", ".tsx", ".js", ".jsx")):
            candidates[fi.path] = "large non-source file"
    suggestions = [
        {"pattern": pattern, "reason": reason}
        for pattern, reason in sorted(candidates.items())
        if pattern not in existing
    ]
    return suggestions[:30]
