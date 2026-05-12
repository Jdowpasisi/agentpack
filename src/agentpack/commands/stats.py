from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table
from rich import box

from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.context_pack import load_pack_metadata
from agentpack.commands._shared import console, _root


def register(app: typer.Typer) -> None:
    @app.command()
    def stats() -> None:
        """Show token-saving statistics and session info."""
        root = _root()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)

        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        meta = load_pack_metadata(root)

        raw = sum(f.estimated_tokens for f in scan_result.all_files)
        after_ignore = sum(f.estimated_tokens for f in scan_result.packable)
        packed = meta.get("token_estimate", 0) if meta else 0
        saving = (1 - packed / raw) * 100 if raw > 0 else 0

        ignored_count = len(scan_result.ignored) + len(scan_result.binary)
        included_count = 0
        summarized_count = 0
        top_files: list[tuple[str, str]] = []

        if meta:
            context_path = root / meta.get("context_path", "")
            if context_path.exists():
                content = context_path.read_text()
                included_count = content.count("Included as: **full**")
                summarized_count = (
                    content.count("Included as: **summary**")
                    + content.count("Included as: **symbols**")
                )

        # --- Session info ---
        from agentpack.session.state import load_session
        session = load_session(root)

        if session:
            sess_tbl = Table(title="Session", box=box.SIMPLE, show_header=False, padding=(0, 2))
            sess_tbl.add_column(style="dim")
            sess_tbl.add_column(style="bold")
            sess_tbl.add_row("active", "[green]yes[/]" if session.active else "[red]no[/]")
            sess_tbl.add_row("agent", session.agent)
            sess_tbl.add_row("mode", session.mode)
            if session.started_at:
                sess_tbl.add_row("started", session.started_at[:19].replace("T", " "))
            if session.last_refresh_at:
                sess_tbl.add_row("last refresh", session.last_refresh_at[:19].replace("T", " "))
            sess_tbl.add_row("refreshes", str(session.refresh_count))
            console.print(sess_tbl)
            console.print()

        # --- Last context top files ---
        metrics_path = root / ".agentpack" / "metrics.jsonl"
        if metrics_path.exists():
            lines = [line.strip() for line in metrics_path.read_text().splitlines() if line.strip()]
            if lines:
                try:
                    json.loads(lines[-1])
                    # metrics don't store per-file data — use context file for top files
                except Exception:
                    pass

        if meta:
            context_path_obj = root / meta.get("context_path", "")
            if context_path_obj.exists():
                top_files = _parse_top_files(context_path_obj)

        token_by_path = {f.path: f.estimated_tokens for f in scan_result.packable}
        top_estimate = sum(token_by_path.get(path, 0) for path, _mode, _why in top_files[:20])
        if top_estimate <= 0:
            full_files = [f for f in scan_result.packable
                          if f.estimated_tokens <= cfg.context.max_file_tokens]
            top_estimate = sum(f.estimated_tokens for f in full_files[:20])
        top_estimate = min(after_ignore, top_estimate)
        vs_top_files = (1 - packed / top_estimate) * 100 if top_estimate > 0 else 0

        # --- Token table ---
        token_tbl = Table(title="Last Context", box=box.SIMPLE, show_header=False, padding=(0, 2))
        token_tbl.add_column(style="dim")
        token_tbl.add_column(justify="right", style="bold")
        token_tbl.add_row("raw repo tokens", f"{raw:,}")
        token_tbl.add_row("after ignore", f"{after_ignore:,}")
        token_tbl.add_row("packed tokens", f"{packed:,}")
        token_tbl.add_row("vs raw repo", f"[green]{saving:.1f}% smaller[/]")
        token_tbl.add_row("vs top-20 full files", f"[green]{vs_top_files:.1f}% smaller[/]")
        token_tbl.add_row("files ignored", f"{ignored_count:,}")
        token_tbl.add_row("files full", f"{included_count:,}")
        token_tbl.add_row("files summarized", f"{summarized_count:,}")
        console.print(token_tbl)

        if top_files:
            console.print()
            top_tbl = Table(title="Top Included", box=box.SIMPLE, show_header=True, padding=(0, 1))
            top_tbl.add_column("#", width=3, style="dim")
            top_tbl.add_column("file", style="cyan", max_width=55)
            top_tbl.add_column("mode", width=8)
            top_tbl.add_column("why", style="dim", max_width=35)
            for i, (path, mode, why) in enumerate(top_files[:10], 1):
                top_tbl.add_row(str(i), path, mode, why)
            console.print(top_tbl)

        # --- Selection accuracy (last 10 runs) ---
        accuracy_rows = _load_accuracy_rows(metrics_path, n=10)
        if accuracy_rows:
            avg_recall = sum(r["selection_recall"] for r in accuracy_rows) / len(accuracy_rows)
            avg_precision = sum(r["selection_precision"] for r in accuracy_rows) / len(accuracy_rows)
            avg_f1 = sum(r["selection_f1"] for r in accuracy_rows) / len(accuracy_rows)
            token_rows = [r for r in accuracy_rows if "selection_token_precision" in r]
            avg_token_precision = (
                sum(r["selection_token_precision"] for r in token_rows) / len(token_rows)
                if token_rows else None
            )
            mode_token_precision: dict[str, float] = {}
            for mode in ("full", "symbols", "summary"):
                key = f"selection_token_precision_{mode}"
                rows = [r for r in accuracy_rows if key in r]
                if rows:
                    mode_token_precision[mode] = sum(r[key] for r in rows) / len(rows)
            console.print()
            acc_tbl = Table(title=f"Selection Accuracy (last {len(accuracy_rows)} runs)", box=box.SIMPLE, show_header=False, padding=(0, 2))
            acc_tbl.add_column(style="dim")
            acc_tbl.add_column(justify="right", style="bold")
            acc_tbl.add_row("avg recall", f"{avg_recall:.1%}")
            acc_tbl.add_row("avg precision", f"{avg_precision:.1%}")
            if avg_token_precision is not None:
                acc_tbl.add_row("avg token precision", f"{avg_token_precision:.1%}")
                for mode, value in mode_token_precision.items():
                    acc_tbl.add_row(f"{mode} token precision", f"{value:.1%}")
            acc_tbl.add_row("avg F1", f"{avg_f1:.1%}")
            console.print(acc_tbl)
            console.print("[dim]recall = how many changed files were in the previous pack[/]")
            if avg_token_precision is not None:
                console.print("[dim]token precision = share of previous pack tokens spent on files later changed[/]")

        console.print("[dim]'top-20 full files' = raw full contents for top included files, capped at 20[/]")


def _load_accuracy_rows(metrics_path: Path, n: int = 10) -> list[dict]:
    """Return up to n most recent metrics records that have accuracy fields."""
    if not metrics_path.exists():
        return []
    try:
        lines = metrics_path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if "selection_recall" in rec:
                rows.append(rec)
                if len(rows) >= n:
                    break
        return rows
    except Exception:
        return []


def _parse_top_files(context_path: Path) -> list[tuple[str, str, str]]:
    """Parse top selected files from context.md. Returns list of (path, mode, why)."""
    results: list[tuple[str, str, str]] = []
    try:
        content = context_path.read_text(encoding="utf-8")
        # Parse the Selected Files table: | `path` | mode | score | why |
        in_table = False
        for line in content.splitlines():
            if line.startswith("| File") or line.startswith("|---|"):
                in_table = True
                continue
            if in_table:
                if not line.startswith("|"):
                    break
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    path = parts[0].strip("`")
                    mode = parts[1]
                    why = parts[3] if len(parts) > 3 else ""
                    results.append((path, mode, why))
    except Exception:
        pass
    return results
