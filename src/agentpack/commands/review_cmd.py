from __future__ import annotations

import importlib.resources
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from agentpack.analysis.tests import find_related_tests
from agentpack.commands._shared import _atomic_write, _now_iso, _root, console
from agentpack.core import git as git_core

_PREFLIGHT_PATH = Path(".agentpack/review-preflight.json")
_RUNBOOK_PATH = Path(".agentpack/review.prompt.md")
_UNDERSTANDING_PROMPT_PATH = Path(".agentpack/review-understanding.prompt.md")
_JUDGE_PROMPT_PATH = Path(".agentpack/review-judge.prompt.md")


def register(app: typer.Typer) -> None:
    @app.command("review")
    def review(
        review_context: str = typer.Argument("", help="Optional reviewer or developer context for this PR review."),
    ) -> None:
        """Prepare the full two-stage PR review bundle for the current branch or PR."""
        root = _root()
        if not git_core.is_git_repo(root):
            console.print("[red]agentpack review requires a git repository.[/]")
            raise typer.Exit(1)

        outputs = _review_output_paths(root)
        preflight = _build_review_preflight(root, review_context.strip(), outputs)
        runbook = _render_review_runbook(preflight)
        understanding_prompt = _render_stage_prompt(
            "stage1-understanding.md",
            preflight,
            output_path=outputs["understanding"],
            prior_path=None,
        )
        judge_prompt = _render_stage_prompt(
            "stage2-judge.md",
            preflight,
            output_path=outputs["findings"],
            prior_path=outputs["understanding"],
        )

        for rel_path, content in {
            _PREFLIGHT_PATH: json.dumps(preflight, indent=2) + "\n",
            _RUNBOOK_PATH: runbook,
            _UNDERSTANDING_PROMPT_PATH: understanding_prompt,
            _JUDGE_PROMPT_PATH: judge_prompt,
        }.items():
            abs_path = root / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(abs_path, content)

        console.print(f"[green]✓[/] Review preflight: [bold]{_PREFLIGHT_PATH}[/]")
        console.print(f"[green]✓[/] Review runbook: [bold]{_RUNBOOK_PATH}[/]")
        console.print(f"[green]✓[/] Stage 1 prompt: [bold]{_UNDERSTANDING_PROMPT_PATH}[/]")
        console.print(f"[green]✓[/] Stage 2 prompt: [bold]{_JUDGE_PROMPT_PATH}[/]")
        console.print(f"[green]✓[/] Stage 1 output target: [bold]{_rel_to_root(outputs['understanding'], root)}[/]")
        console.print(f"[green]✓[/] Stage 2 output target: [bold]{_rel_to_root(outputs['findings'], root)}[/]")
        if preflight["warnings"]:
            console.print("[yellow]Warnings:[/]")
            for warning in preflight["warnings"]:
                console.print(f"  - {warning}")
        console.print("Use the runbook from your agent host; it drives understanding, then judge, against exact diff and code evidence.")


def _build_review_preflight(root: Path, review_context: str, outputs: dict[str, Path]) -> dict[str, Any]:
    branch = git_core.current_branch(root) or "HEAD"
    sha = git_core.current_sha(root) or ""
    pr = _gh_pr_metadata(root)
    all_paths = _repo_paths(root)
    diff_info = _diff_base(root, pr)
    changed_paths = _changed_paths(root, diff_info["range"])
    changed_files = [
        {
            "path": path,
            "related_tests": find_related_tests(path, all_paths),
        }
        for path in changed_paths
    ]
    warnings = _warnings(root, pr, diff_info, changed_paths)

    return {
        "generated_at": _now_iso(),
        "review_context": review_context,
        "git": {
            "branch": branch,
            "branch_prefix": outputs["branch_prefix"],
            "head_sha": sha,
            "dirty_files": sorted(git_core.dirty_files(root)),
        },
        "pr": pr,
        "diff": {
            "range": diff_info["range"],
            "base_ref": diff_info["base_ref"],
            "source": diff_info["source"],
            "changed_files_count": len(changed_files),
        },
        "paths": {
            "preflight": str(_PREFLIGHT_PATH),
            "runbook": str(_RUNBOOK_PATH),
            "understanding_prompt": str(_UNDERSTANDING_PROMPT_PATH),
            "judge_prompt": str(_JUDGE_PROMPT_PATH),
            "understanding_output": _rel_to_root(outputs["understanding"], root),
            "findings_output": _rel_to_root(outputs["findings"], root),
        },
        "changed_files": changed_files,
        "warnings": warnings,
    }


def _review_output_paths(root: Path) -> dict[str, Any]:
    branch = git_core.current_branch(root) or "HEAD"
    branch_prefix = branch.replace("/", "-")
    understanding = root / f"{branch_prefix}_understanding.json"
    findings = root / f"{branch_prefix}_findings.json"
    return {
        "branch_prefix": branch_prefix,
        "understanding": understanding,
        "findings": findings,
    }


def _render_review_runbook(preflight: dict[str, Any]) -> str:
    return (
        "# AgentPack Review Workflow\n\n"
        "Run the full two-stage review flow for the current PR or branch. Treat the source of truth as the latest PR head, "
        "`gh pr view`, `git diff`, and direct reads of exact changed code. The reviewer context below is a prioritization "
        "lens only; it must not replace code evidence.\n\n"
        "## Reviewer Context\n\n"
        f"{preflight['review_context'] or '(none)'}\n\n"
        "## Preflight\n\n"
        f"- Branch: {preflight['git']['branch']}\n"
        f"- Branch prefix: {preflight['git']['branch_prefix']}\n"
        f"- Head SHA: {preflight['git']['head_sha']}\n"
        f"- Diff range: {preflight['diff']['range']}\n"
        f"- Diff source: {preflight['diff']['source']}\n"
        f"- Changed files: {preflight['diff']['changed_files_count']}\n"
        + (f"- PR: #{preflight['pr']['number']} — {preflight['pr']['title']}\n" if preflight.get("pr") else "")
        + (f"- PR URL: {preflight['pr']['url']}\n" if preflight.get("pr") and preflight["pr"].get("url") else "")
        + "\n## Generated Artifacts\n\n"
        f"- Preflight JSON: `{preflight['paths']['preflight']}`\n"
        f"- Stage 1 prompt: `{preflight['paths']['understanding_prompt']}`\n"
        f"- Stage 2 prompt: `{preflight['paths']['judge_prompt']}`\n"
        f"- Stage 1 output: `{preflight['paths']['understanding_output']}`\n"
        f"- Stage 2 output: `{preflight['paths']['findings_output']}`\n\n"
        "## Workflow\n\n"
        "1. Read the Stage 1 prompt file completely and produce the understanding JSON at the declared output path.\n"
        "2. Confirm the understanding JSON parses before moving on.\n"
        "3. Read the Stage 2 prompt file completely and produce the findings JSON at the declared output path.\n"
        "4. Confirm the findings JSON parses before reporting back.\n"
        "5. In the final user-facing response, summarize findings and validation gaps without exposing internal stage names.\n"
    )


def _render_stage_prompt(
    template_name: str,
    preflight: dict[str, Any],
    *,
    output_path: Path,
    prior_path: Path | None,
) -> str:
    root = _root().resolve()
    abs_output = output_path.resolve()
    lines = [
        "# AgentPack Review Stage",
        "",
        "## AgentPack Context",
        "",
        f"- Reviewer context: {preflight['review_context'] or '(none)'}",
        f"- Preflight JSON: {preflight['paths']['preflight']}",
        f"- Diff range: {preflight['diff']['range']}",
        f"- Diff source: {preflight['diff']['source']}",
        f"- Output path: {_rel_to_root(abs_output, root)}",
    ]
    if prior_path is not None:
        lines.append(f"- Input path: {_rel_to_root(prior_path.resolve(), root)}")
    if preflight["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in preflight["warnings"])
    lines.extend(["", "## Stage Prompt", "", _load_review_template(template_name)])
    return "\n".join(lines).rstrip() + "\n"


def _load_review_template(name: str) -> str:
    try:
        return (
            importlib.resources.files("agentpack")
            .joinpath("data", "review", name)
            .read_text(encoding="utf-8")
        )
    except Exception:
        return (
            Path(__file__).resolve().parents[1] / "data" / "review" / name
        ).read_text(encoding="utf-8")


def _gh_pr_metadata(root: Path) -> dict[str, Any] | None:
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            "--json",
            "number,title,url,baseRefName,headRefName",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return {
        "number": payload.get("number"),
        "title": payload.get("title", ""),
        "url": payload.get("url", ""),
        "base_ref": payload.get("baseRefName", ""),
        "head_ref": payload.get("headRefName", ""),
    }


def _repo_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _diff_base(root: Path, pr: dict[str, Any] | None) -> dict[str, str]:
    base_name = (pr or {}).get("base_ref", "")
    for candidate in _base_candidates(base_name):
        if _git_ref_exists(root, candidate):
            return {
                "base_ref": candidate,
                "range": f"{candidate}...HEAD",
                "source": "pr-base",
            }
    if _git_ref_exists(root, "HEAD~1"):
        return {
            "base_ref": "HEAD~1",
            "range": "HEAD~1..HEAD",
            "source": "previous-commit",
        }
    return {
        "base_ref": "HEAD",
        "range": "HEAD",
        "source": "head-only",
    }


def _base_candidates(base_name: str) -> list[str]:
    candidates: list[str] = []
    if base_name:
        candidates.extend([f"origin/{base_name}", base_name])
    return candidates


def _git_ref_exists(root: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _changed_paths(root: Path, diff_range: str) -> list[str]:
    if diff_range == "HEAD":
        return sorted(git_core.changed_files(root) | git_core.untracked_files(root))
    args = ["git", "diff", "--name-only", diff_range]
    result = subprocess.run(args, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _warnings(root: Path, pr: dict[str, Any] | None, diff_info: dict[str, str], changed_paths: list[str]) -> list[str]:
    warnings: list[str] = []
    dirty = sorted(git_core.dirty_files(root))
    if dirty:
        warnings.append(f"dirty tree has {len(dirty)} path(s); review the checked-out PR head, not local edits")
    if not pr:
        warnings.append("gh PR metadata unavailable; review is using local git context only")
    if diff_info["source"] != "pr-base":
        warnings.append(f"diff base fell back to {diff_info['base_ref']}")
    if not changed_paths:
        warnings.append("no changed files detected for the selected diff range")
    generated = [path for path in changed_paths if path.startswith(".agentpack/")]
    if generated:
        warnings.append("generated AgentPack artifacts are in the diff; keep them low priority unless the change is about distribution or docs")
    return warnings


def _rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
