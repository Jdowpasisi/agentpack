from __future__ import annotations

import sys

import typer

from agentpack.commands._shared import _root
from agentpack.core.config import load_config
from agentpack.output_compression import compress_output
from agentpack.session.events import record_event


def register(app: typer.Typer) -> None:
    @app.command("compress-output")
    def compress_output_cmd(
        file: str = typer.Argument("-", help="Output file to summarize, or '-' for stdin."),
        kind: str = typer.Option("auto", "--kind", help="Output kind: auto|pytest|npm|git-diff|rg|ls."),
    ) -> None:
        """Summarize noisy command output while preserving actionable lines."""
        root = _root()
        cfg = load_config(root)
        if file == "-":
            content = sys.stdin.read()
        else:
            content = (root / file).read_text(encoding="utf-8", errors="replace")
        result = compress_output(content, kind=kind, max_items=cfg.runtime.max_output_summary_items)
        record_event(
            root,
            "compress_output",
            {"kind": kind, "input_chars": len(content), "output_chars": len(result)},
            output_path=cfg.runtime.session_events_output,
        )
        typer.echo(result, nl=False)
