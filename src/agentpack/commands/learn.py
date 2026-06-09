from __future__ import annotations

import json
from datetime import datetime

import typer

from agentpack.commands._shared import _atomic_write, _root, console
from agentpack.core.config import load_config
from agentpack.learning.collector import collect_learning_inputs
from agentpack.learning.extractor import build_learning_report
from agentpack.learning.feedback import record_learning_feedback
from agentpack.learning.quality import score_learning_report
from agentpack.learning.renderers import (
    learning_report_to_dict,
    render_agent_lessons_markdown,
    render_llm_prompt_markdown,
    render_learning_markdown,
    render_pr_comment_markdown,
)
from agentpack.learning.skill_map import update_skill_map


def register(app: typer.Typer) -> None:
    @app.command()
    def learn(
        task: str = typer.Option("auto", "--task", help="Task source. Only 'auto' is supported."),
        since: str | None = typer.Option(None, "--since", help="Git ref to compare against, e.g. HEAD~1 or main."),
        today: bool = typer.Option(False, "--today", help="Use today's work scope label for the report."),
        output: str = typer.Option("", "--output", "-o", help="Markdown output path."),
        json_output: bool = typer.Option(False, "--json", help="Print JSON to stdout instead of writing Markdown."),
        llm_prompt: bool = typer.Option(False, "--llm-prompt", help="Write an LLM-ready learning prompt artifact."),
        pr_comment: bool = typer.Option(False, "--pr-comment", help="Write a PR-comment-ready learning summary artifact."),
        feedback: str = typer.Option("", "--feedback", help="Record feedback for this learning output (helpful|not-helpful)."),
        feedback_note: str = typer.Option("", "--feedback-note", help="Optional note stored with --feedback."),
    ) -> None:
        """Generate local learning artifacts from current task and git changes."""
        if task != "auto":
            console.print(
                "[red]`agentpack learn --task \"...\"` is not supported. "
                "Write .agentpack/task.md and use --task auto.[/]"
            )
            raise typer.Exit(2)

        root = _root()
        cfg = load_config(root)
        since_date = _today_start_iso() if today and not since else None
        inputs = collect_learning_inputs(
            root,
            since=since,
            since_date=since_date,
            max_changed_files=cfg.learning.max_changed_files,
            max_diff_chars_per_file=cfg.learning.max_diff_chars_per_file,
        )
        report = build_learning_report(
            inputs,
            max_cards=cfg.learning.max_cards,
            max_quiz_questions=cfg.learning.max_quiz_questions,
        )
        if today:
            report.scope = "today"
            if since_date:
                report.since = f"today ({since_date})"

        update_skill_map(root / cfg.learning.skill_map_output, report.skill_evidence)
        agent_lessons_path = root / cfg.learning.agent_lessons_output
        agent_lessons_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(agent_lessons_path, render_agent_lessons_markdown(report))

        quality = score_learning_report(report)
        if quality.score < cfg.learning.min_groundedness_score:
            console.print(f"[yellow]Learning quality warning:[/] score {quality.score}; " + "; ".join(quality.issues))

        if llm_prompt:
            prompt_path = root / cfg.learning.llm_prompt_output
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(prompt_path, render_llm_prompt_markdown(report))
        if pr_comment:
            pr_path = root / cfg.learning.pr_comment_output
            pr_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(pr_path, render_pr_comment_markdown(report))
        if feedback:
            if feedback not in {"helpful", "not-helpful"}:
                console.print("[red]--feedback must be helpful or not-helpful.[/]")
                raise typer.Exit(2)
            record_learning_feedback(root / cfg.learning.feedback_output, report, feedback, feedback_note)

        if json_output:
            typer.echo(json.dumps(learning_report_to_dict(report), indent=2, sort_keys=True))
            return

        default_output = cfg.learning.daily_output if today else cfg.learning.markdown_output
        out_path = root / (output or default_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out_path, render_learning_markdown(report))
        console.print(f"[green]✓[/] Wrote {out_path.relative_to(root)}")


def _today_start_iso() -> str:
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
