from __future__ import annotations

import json
from datetime import datetime

import typer

from agentpack.commands._shared import _atomic_write, _root, console
from agentpack.commands.dashboard import _open_file
from agentpack.core.config import load_config
from agentpack.learning.collector import collect_learning_inputs
from agentpack.learning.extractor import build_learning_report
from agentpack.learning.feedback import apply_feedback_to_report, load_feedback_summary, record_learning_feedback
from agentpack.learning.lesson_ranker import rank_agent_lessons
from agentpack.learning.provider import LearningProviderError, run_concept_provider_command, run_provider_command
from agentpack.learning.quality import score_learning_report
from agentpack.learning.renderers import (
    learning_report_to_dict,
    render_dashboard_html,
    render_agent_lessons_markdown,
    render_drills_markdown,
    render_llm_prompt_markdown,
    render_learning_markdown,
    render_pr_comment_markdown,
    render_provider_preview_markdown,
    render_quality_markdown,
    render_team_lessons_markdown,
)
from agentpack.learning.skill_map import apply_skill_feedback, recommend_practice_drills, render_skill_summary, update_skill_map


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
        provider_preview: bool = typer.Option(False, "--provider-preview", help="Print the bounded provider payload without making a network call."),
        provider_command: str = typer.Option("", "--provider-command", help="Run a local JSON-in/JSON-out provider command to enrich the report."),
        concept_provider_command: str = typer.Option(
            "",
            "--concept-provider-command",
            help="Run a local JSON-in/JSON-out provider command to enrich detected learning concepts.",
        ),
        no_concept_provider: bool = typer.Option(
            False,
            "--no-concept-provider",
            help="Disable configured concept provider enrichment for this run.",
        ),
        dashboard: bool = typer.Option(False, "--dashboard", help="Write a static HTML learning dashboard artifact."),
        open_dashboard: bool = typer.Option(False, "--open", help="Open the generated learning dashboard in a browser."),
        team_export: bool = typer.Option(False, "--team-export", help="Write an opt-in team lesson export without personal skill history."),
        ci: bool = typer.Option(False, "--ci", help="Fail when learning quality is below the configured threshold."),
        skills: bool = typer.Option(False, "--skills", help="Print the local skill memory summary and exit."),
        drills: bool = typer.Option(False, "--drills", help="Print recommended practice drills from local skill memory and exit."),
        feedback: str = typer.Option("", "--feedback", help="Record feedback for this learning output (helpful|not-helpful)."),
        feedback_note: str = typer.Option("", "--feedback-note", help="Optional note stored with --feedback."),
        feedback_target: str = typer.Option("", "--feedback-target", help="Optional target such as skill:CLI design, lesson:retry, rename:old=>new, or merge:old=>new."),
        suppress_skill: str = typer.Option("", "--suppress-skill", help="Suppress a noisy skill in future skill views and generation."),
        rename_skill: str = typer.Option("", "--rename-skill", help="Rename a skill using old=>new."),
        merge_skill: str = typer.Option("", "--merge-skill", help="Merge a skill using old=>new."),
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
        skill_map_path = root / cfg.learning.skill_map_output
        if skills:
            typer.echo(render_skill_summary(skill_map_path), nl=False)
            return
        if drills:
            typer.echo(render_drills_markdown(recommend_practice_drills(skill_map_path)), nl=False)
            return
        if suppress_skill:
            apply_skill_feedback(skill_map_path, target=suppress_skill, action="suppress", note=feedback_note)
            console.print(f"[green]✓[/] Suppressed skill {suppress_skill}")
            return
        if rename_skill:
            old, new = _split_mapping(rename_skill, "--rename-skill")
            apply_skill_feedback(skill_map_path, target=old, action="rename", replacement=new, note=feedback_note)
            console.print(f"[green]✓[/] Renamed skill {old} -> {new}")
            return
        if merge_skill:
            old, new = _split_mapping(merge_skill, "--merge-skill")
            apply_skill_feedback(skill_map_path, target=old, action="merge", replacement=new, note=feedback_note)
            console.print(f"[green]✓[/] Merged skill {old} -> {new}")
            return

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
        feedback_summary = load_feedback_summary(root / cfg.learning.feedback_output)
        report = apply_feedback_to_report(report, feedback_summary)
        report.agent_lessons = rank_agent_lessons(report, feedback_summary, limit=cfg.learning.max_cards)
        if today:
            report.scope = "today"
            if since_date:
                report.since = f"today ({since_date})"

        if provider_preview:
            typer.echo(render_provider_preview_markdown(report), nl=False)
            return

        concept_command = concept_provider_command or ("" if no_concept_provider else cfg.learning.concept_provider_command)
        if concept_command:
            try:
                report = run_concept_provider_command(
                    concept_command,
                    inputs,
                    report,
                    timeout_seconds=cfg.learning.concept_provider_timeout_seconds,
                )
            except LearningProviderError as exc:
                if concept_provider_command or cfg.learning.concept_provider_required:
                    console.print(f"[red]Concept provider command failed:[/] {exc}")
                    raise typer.Exit(1) from exc
                console.print(f"[yellow]Concept provider skipped:[/] {exc}")

        command = provider_command or cfg.learning.provider_command
        if command:
            try:
                report = run_provider_command(command, report, timeout_seconds=cfg.learning.provider_timeout_seconds)
            except LearningProviderError as exc:
                console.print(f"[red]Provider command failed:[/] {exc}")
                raise typer.Exit(1) from exc

        update_skill_map(skill_map_path, report.skill_evidence)
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
        if open_dashboard:
            dashboard = True
        if dashboard:
            dashboard_path = root / cfg.learning.dashboard_output
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(dashboard_path, render_dashboard_html(report))
            console.print(f"[green]✓[/] Wrote {dashboard_path.relative_to(root)}")
            if open_dashboard:
                _open_file(dashboard_path)
        if team_export:
            team_path = root / cfg.learning.team_lessons_output
            team_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(team_path, render_team_lessons_markdown(report))
        if feedback:
            if feedback not in {"helpful", "not-helpful"}:
                console.print("[red]--feedback must be helpful or not-helpful.[/]")
                raise typer.Exit(2)
            record_learning_feedback(root / cfg.learning.feedback_output, report, feedback, feedback_note, feedback_target)
        if ci:
            typer.echo(render_quality_markdown(report, quality.score, quality.issues), nl=False)
            if quality.score < cfg.learning.min_groundedness_score:
                raise typer.Exit(1)

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


def _split_mapping(value: str, flag: str) -> tuple[str, str]:
    if "=>" not in value:
        console.print(f"[red]{flag} expects old=>new.[/]")
        raise typer.Exit(2)
    old, new = [part.strip() for part in value.split("=>", 1)]
    if not old or not new:
        console.print(f"[red]{flag} expects non-empty old=>new values.[/]")
        raise typer.Exit(2)
    return old, new
