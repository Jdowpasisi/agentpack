from __future__ import annotations

import json

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def monitor(
        last: int = typer.Option(20, "--last", "-n", help="Show last N pack runs."),
        clear: bool = typer.Option(False, "--clear", help="Delete metrics log."),
    ) -> None:
        """Show pack performance metrics across runs."""
        root = _root()
        metrics_path = root / ".agentpack" / "metrics.jsonl"

        if clear:
            if metrics_path.exists():
                metrics_path.unlink()
                console.print("[green]Metrics log cleared.[/]")
            else:
                console.print("[dim]No metrics log found.[/]")
            return

        if not metrics_path.exists():
            console.print("[yellow]No metrics recorded yet. Run agentpack pack first.[/]")
            raise typer.Exit(1)

        records = []
        for line in metrics_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        if not records:
            console.print("[yellow]Metrics log is empty.[/]")
            raise typer.Exit(1)

        recent = records[-last:]

        # Summary stats
        savings = [r["saving_pct"] for r in recent]
        totals = [r["total_s"] for r in recent]
        avg_saving = sum(savings) / len(savings)
        avg_total = sum(totals) / len(totals)
        best_saving = max(savings)

        summary_table = Table(title="Performance Summary", show_header=True, box=box.SIMPLE)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", justify="right")
        summary_table.add_row("Runs recorded", str(len(records)))
        summary_table.add_row("Shown", str(len(recent)))
        summary_table.add_row("Avg saving", f"[green]{avg_saving:.1f}%[/]")
        summary_table.add_row("Best saving", f"[green]{best_saving:.1f}%[/]")
        summary_table.add_row("Avg pack time", f"{avg_total:.2f}s")
        console.print(summary_table)

        # Per-run table
        run_table = Table(title=f"Last {len(recent)} Runs", show_header=True, box=box.SIMPLE)
        run_table.add_column("When", style="dim", max_width=20)
        run_table.add_column("Task", max_width=35)
        run_table.add_column("Mode", width=9)
        run_table.add_column("Saving", justify="right")
        run_table.add_column("Packed", justify="right")
        run_table.add_column("Total", justify="right")
        run_table.add_column("scan", justify="right", style="dim")
        run_table.add_column("sum", justify="right", style="dim")
        run_table.add_column("rank", justify="right", style="dim")

        for r in recent:
            ts = r.get("ts", "")[:16].replace("T", " ")
            phases = r.get("phases", {})
            run_table.add_row(
                ts,
                r.get("task", "")[:35],
                r.get("mode", ""),
                f"[green]{r['saving_pct']:.1f}%[/]",
                f"{r['packed_tokens']:,}",
                f"{r['total_s']:.2f}s",
                f"{phases.get('scan', 0):.2f}s",
                f"{phases.get('summarize', 0):.2f}s",
                f"{phases.get('rank', 0):.2f}s",
            )

        console.print(run_table)

        # Phase breakdown averaged
        phase_keys = ["scan", "summarize", "deps", "changes", "rank", "select", "render"]
        phase_table = Table(title="Avg Phase Times", show_header=True, box=box.SIMPLE)
        phase_table.add_column("Phase", style="cyan")
        phase_table.add_column("Avg (s)", justify="right")
        phase_table.add_column("Max (s)", justify="right")
        for pk in phase_keys:
            vals = [r.get("phases", {}).get(pk, 0) for r in recent]
            if any(v > 0 for v in vals):
                phase_table.add_row(pk, f"{sum(vals)/len(vals):.3f}", f"{max(vals):.3f}")
        console.print(phase_table)
