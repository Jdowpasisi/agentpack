from __future__ import annotations

import importlib.resources
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer

from agentpack.analysis.tests import find_related_tests
from agentpack.application.pack_service import PackRequest, PackService
from agentpack.commands._shared import _atomic_write, _now_iso, _root, console
from agentpack.core import git as git_core
from agentpack.core.citations import (
    CitationValidation,
    extract_location_citations,
    parse_location,
    semantic_support_command_judge,
    validate_citations,
    validate_claim_support,
)
from agentpack.core.models import Citation
from agentpack.core.toon_parser import ToonParseError, load_toon

_PREFLIGHT_PATH = Path(".agentpack/review-preflight.json")
_RUNBOOK_PATH = Path(".agentpack/review.prompt.md")
_UNDERSTANDING_PROMPT_PATH = Path(".agentpack/review-understanding.prompt.md")
_JUDGE_PROMPT_PATH = Path(".agentpack/review-judge.prompt.md")
_STATE_PATH = Path(".agentpack/review-state.json")
_REVIEW_RUNS_DIR = Path(".agentpack/reviews")
_LLM_REVIEW_FORMAT = "TOON"
_PR_URL_RE = re.compile(r"https?://\S+/pull/(?P<number>\d+)\b", re.IGNORECASE)
_PR_CONTEXT_RE = re.compile(
    r"(?:\b(?:pr|pull request)\s*#?\s*(?P<number>\d+)\b|\bgh\s+pr\s+(?:view|diff|checkout)\s+(?P<gh_number>\d+)\b)",
    re.IGNORECASE,
)


class _ReviewPreflightError(Exception):
    pass


def register(app: typer.Typer) -> None:
    @app.command("review")
    def review(
        review_context: str = typer.Argument("", help="Optional reviewer or developer context for this PR review."),
        resume: str = typer.Option("", "--resume", help="Resume a previous review run by run id."),
        pr_target: str = typer.Option("", "--pr", help="PR number or URL to review. Binds diff/context to that PR."),
        allow_local_fallback: bool = typer.Option(
            False,
            "--allow-local-fallback",
            help="Allow local HEAD-based diff fallback when GitHub PR metadata or fetch is unavailable.",
        ),
        check: bool = typer.Option(False, "--check", help="Validate active review stage artifacts and print the next gate."),
    ) -> None:
        """Prepare the full two-stage PR review bundle for the current branch or PR."""
        root = _root()
        if not git_core.is_git_repo(root):
            console.print("[red]agentpack review requires a git repository.[/]")
            raise typer.Exit(1)

        if check:
            _check_active_review(root)
            return

        if resume.strip():
            preflight = _load_review_run(root, resume.strip())
            outputs = _review_output_paths(
                root,
                branch_prefix=preflight["review"]["branch_prefix"],
                run_id=preflight["review"]["run_id"],
            )
        else:
            target, cleaned_context = _parse_review_target(pr_target.strip(), review_context.strip())
            outputs = _review_output_paths(root, branch_prefix=_target_branch_prefix(target))
            try:
                preflight = _build_review_preflight(
                    root,
                    cleaned_context,
                    outputs,
                    target=target,
                    allow_local_fallback=allow_local_fallback,
                )
            except _ReviewPreflightError as exc:
                console.print(f"[red]Review preflight blocked:[/] {exc}")
                raise typer.Exit(1) from exc

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

        artifacts = {
            outputs["preflight"]: json.dumps(preflight, indent=2) + "\n",
            outputs["runbook"]: runbook,
            outputs["understanding_prompt"]: understanding_prompt,
            outputs["judge_prompt"]: judge_prompt,
            outputs["state"]: json.dumps(_review_state(root, preflight), indent=2) + "\n",
            _PREFLIGHT_PATH: json.dumps(preflight, indent=2) + "\n",
            _RUNBOOK_PATH: runbook,
            _UNDERSTANDING_PROMPT_PATH: understanding_prompt,
            _JUDGE_PROMPT_PATH: judge_prompt,
            _STATE_PATH: json.dumps(_review_state(root, preflight), indent=2) + "\n",
        }
        for rel_path, content in artifacts.items():
            abs_path = root / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(abs_path, content)

        console.print(f"[green]✓[/] Review run id: [bold]{preflight['review']['run_id']}[/]")
        console.print(f"[green]✓[/] Review run dir: [bold]{preflight['paths']['run_dir']}[/]")
        console.print(f"[green]✓[/] Review preflight: [bold]{_PREFLIGHT_PATH}[/]")
        console.print(f"[green]✓[/] Review runbook: [bold]{_RUNBOOK_PATH}[/]")
        console.print(f"[green]✓[/] Stage 1 prompt: [bold]{_UNDERSTANDING_PROMPT_PATH}[/]")
        console.print(f"[green]✓[/] Stage 2 prompt: [bold]{_JUDGE_PROMPT_PATH}[/]")
        console.print(f"[green]✓[/] Stage 1 output target: [bold]{_rel_to_root(outputs['understanding'], root)}[/]")
        console.print(f"[green]✓[/] Stage 2 output target: [bold]{_rel_to_root(outputs['findings'], root)}[/]")
        console.print(f"[green]✓[/] Review stage state: [bold]{_STATE_PATH}[/]")
        if preflight["warnings"]:
            console.print("[yellow]Warnings:[/]")
            for warning in preflight["warnings"]:
                console.print(f"  - {warning}")
        console.print("Use the runbook from your agent host; run `agentpack review --check` after each stage before continuing.")


def _build_review_preflight(
    root: Path,
    review_context: str,
    outputs: dict[str, Any],
    *,
    target: dict[str, Any] | None = None,
    allow_local_fallback: bool = False,
) -> dict[str, Any]:
    branch = outputs["branch"]
    pr = _gh_pr_metadata(root, target)
    all_paths = _repo_paths(root)
    diff_info = _diff_base(root, pr, target=target, allow_local_fallback=allow_local_fallback)
    sha = diff_info.get("head_sha") or git_core.current_sha(root) or ""
    changed_paths = _changed_paths(root, diff_info["range"])
    changed_files = [
        {
            "path": path,
            "related_tests": find_related_tests(path, all_paths),
        }
        for path in changed_paths
    ]
    warnings, info = _warnings(root, pr, diff_info, changed_paths)
    context_pack = _build_review_context_pack(root, review_context, diff_info, outputs, warnings)
    review_target = _preflight_target(target, pr)

    return {
        "generated_at": _now_iso(),
        "review_context": review_context,
        "review": {
            "mode": "fresh",
            "run_id": outputs["run_id"],
            "branch": branch,
            "branch_prefix": outputs["branch_prefix"],
            "target": review_target,
        },
        "execution_contract": {
            "structured_format": _LLM_REVIEW_FORMAT,
            "requires_write_to_file": True,
            "requires_read_file_between_stages": True,
            "forbid_inline_review": True,
            "blocked_without_stage_artifact": True,
            "stage_order": ["understanding", "judge"],
        },
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
            "head_ref": diff_info.get("head_ref", ""),
            "source": diff_info["source"],
            "changed_files_count": len(changed_files),
        },
        "paths": {
            "run_dir": _rel_to_root(outputs["run_dir"], root),
            "preflight": _rel_to_root(outputs["preflight"], root),
            "runbook": _rel_to_root(outputs["runbook"], root),
            "understanding_prompt": _rel_to_root(outputs["understanding_prompt"], root),
            "judge_prompt": _rel_to_root(outputs["judge_prompt"], root),
            "understanding_output": _rel_to_root(outputs["understanding"], root),
            "findings_output": _rel_to_root(outputs["findings"], root),
            "state": _rel_to_root(outputs["state"], root),
            "active_preflight": str(_PREFLIGHT_PATH),
            "active_runbook": str(_RUNBOOK_PATH),
            "active_understanding_prompt": str(_UNDERSTANDING_PROMPT_PATH),
            "active_judge_prompt": str(_JUDGE_PROMPT_PATH),
            "active_state": str(_STATE_PATH),
        },
        "context_pack": context_pack,
        "changed_files": changed_files,
        "warnings": warnings,
        "info": info,
    }


def _review_output_paths(
    root: Path,
    *,
    branch_prefix: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    branch = git_core.current_branch(root) or "HEAD"
    branch_prefix = branch_prefix or branch.replace("/", "-")
    run_id = run_id or _new_review_run_id()
    run_dir = root / _REVIEW_RUNS_DIR / branch_prefix / run_id
    return {
        "branch": branch,
        "branch_prefix": branch_prefix,
        "run_id": run_id,
        "run_dir": run_dir,
        "preflight": run_dir / "preflight.json",
        "runbook": run_dir / "runbook.md",
        "understanding_prompt": run_dir / "understanding.prompt.md",
        "judge_prompt": run_dir / "judge.prompt.md",
        "understanding": run_dir / "understanding.toon",
        "findings": run_dir / "findings.toon",
        "state": run_dir / "state.json",
    }


def _new_review_run_id() -> str:
    return f"{_now_iso().replace(':', '').replace('-', '').replace('.', '')}-{uuid4().hex[:8]}"


def _parse_review_target(raw_pr: str, review_context: str) -> tuple[dict[str, Any] | None, str]:
    if raw_pr:
        return _target_from_raw(raw_pr, source="option"), review_context
    url_match = _PR_URL_RE.search(review_context)
    if url_match:
        target = _target_from_raw(url_match.group(0), source="argument")
        cleaned = _clean_review_context(review_context[:url_match.start()] + review_context[url_match.end():])
        return target, cleaned
    match = _PR_CONTEXT_RE.search(review_context)
    if not match:
        return None, review_context
    number = match.group("number") or match.group("gh_number") or ""
    target = _target_from_raw(number, source="argument")
    cleaned = _clean_review_context(review_context[:match.start()] + review_context[match.end():])
    return target, cleaned


def _target_from_raw(raw: str, *, source: str) -> dict[str, Any]:
    value = raw.strip()
    url_match = _PR_URL_RE.search(value)
    number = url_match.group("number") if url_match else value.lstrip("#")
    if not number.isdigit():
        number_match = re.search(r"\b(\d+)\b", value)
        number = number_match.group(1) if number_match else ""
    return {
        "raw": value,
        "number": int(number) if number.isdigit() else None,
        "url": url_match.group(0) if url_match else "",
        "source": source,
    }


def _target_branch_prefix(target: dict[str, Any] | None) -> str | None:
    if not target or not target.get("number"):
        return None
    return f"pr-{target['number']}"


def _target_cli_arg(target: dict[str, Any] | None) -> str | None:
    if not target:
        return None
    if target.get("url"):
        return str(target["url"])
    if target.get("number"):
        return str(target["number"])
    raw = str(target.get("raw") or "").strip()
    return raw or None


def _clean_review_context(value: str) -> str:
    return " ".join(value.replace("  ", " ").strip(" -:\t").split())


def _preflight_target(target: dict[str, Any] | None, pr: dict[str, Any] | None) -> dict[str, Any]:
    if target:
        return {
            "raw": target.get("raw", ""),
            "number": target.get("number") or (pr or {}).get("number"),
            "url": target.get("url") or (pr or {}).get("url", ""),
            "source": target.get("source", ""),
        }
    if pr:
        return {
            "raw": "",
            "number": pr.get("number"),
            "url": pr.get("url", ""),
            "source": "current-branch",
        }
    return {"raw": "", "number": None, "url": "", "source": "local-fallback"}


def _load_review_run(root: Path, run_id: str) -> dict[str, Any]:
    branch = git_core.current_branch(root) or "HEAD"
    branch_prefix = branch.replace("/", "-")
    preflight_path = root / _REVIEW_RUNS_DIR / branch_prefix / run_id / "preflight.json"
    if not preflight_path.exists():
        matches = sorted((root / _REVIEW_RUNS_DIR).glob(f"*/{run_id}/preflight.json"))
        if len(matches) == 1:
            preflight_path = matches[0]
        else:
            console.print(f"[red]Review run not found:[/] {preflight_path}")
            raise typer.Exit(1)
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        console.print(f"[red]Review run preflight is invalid JSON:[/] {preflight_path}")
        raise typer.Exit(1)
    understanding_path = preflight_path.parent / "understanding.toon"
    findings_path = preflight_path.parent / "findings.toon"
    try:
        if understanding_path.exists():
            _validate_review_artifact(understanding_path, kind="understanding")
        if findings_path.exists():
            _validate_review_artifact(findings_path, kind="findings")
    except ValueError as exc:
        console.print(f"[red]Review run artifact invalid:[/] {exc}")
        raise typer.Exit(1)
    preflight.setdefault("review", {})
    preflight["review"]["mode"] = "resume"
    return preflight


def _render_review_runbook(preflight: dict[str, Any]) -> str:
    target = preflight["review"].get("target", {})
    return (
        "# AgentPack Review Workflow\n\n"
        "Run the full two-stage review flow for the current PR or branch. Treat the source of truth as the latest PR head, "
        "`gh pr view`, `git diff`, and direct reads of exact changed code. The reviewer context below is a prioritization "
        "lens only; it must not replace code evidence.\n\n"
        "## Reviewer Context\n\n"
        f"{preflight['review_context'] or '(none)'}\n\n"
        "## AgentPack Context Preflight\n\n"
        "Before reading PR diff or code, refresh AgentPack context for this exact review task. "
        "Prefer MCP `agentpack_pack_context(task=\"review current PR ...\")`; if MCP is unavailable, "
        "use the current AgentPack CLI refresh command. If you bypass this, state the bypass reason.\n\n"
        "## Preflight\n\n"
        f"- Review mode: {preflight['review'].get('mode', 'fresh')}\n"
        f"- Review run id: {preflight['review']['run_id']}\n"
        f"- Review run dir: {preflight['paths']['run_dir']}\n"
        f"- Branch: {preflight['git']['branch']}\n"
        f"- Branch prefix: {preflight['git']['branch_prefix']}\n"
        f"- Head SHA: {preflight['git']['head_sha']}\n"
        f"- Diff range: {preflight['diff']['range']}\n"
        f"- Diff source: {preflight['diff']['source']}\n"
        + (f"- Review target: PR #{target['number']} ({target['source']})\n" if target.get("number") else "")
        + f"- Changed files: {preflight['diff']['changed_files_count']}\n"
        + (f"- AgentPack context: `{preflight['context_pack']['path']}` ({preflight['context_pack']['tokens']} tokens)\n" if preflight.get("context_pack", {}).get("path") else "")
        + (f"- PR: #{preflight['pr']['number']} — {preflight['pr']['title']}\n" if preflight.get("pr") else "")
        + (f"- PR URL: {preflight['pr']['url']}\n" if preflight.get("pr") and preflight["pr"].get("url") else "")
        + "\n## Generated Artifacts\n\n"
        + f"- Preflight JSON: `{preflight['paths']['preflight']}`\n"
        f"- Stage 1 prompt: `{preflight['paths']['understanding_prompt']}`\n"
        f"- Stage 2 prompt: `{preflight['paths']['judge_prompt']}`\n"
        f"- Stage 1 output ({_LLM_REVIEW_FORMAT}): `{preflight['paths']['understanding_output']}`\n"
        f"- Stage 2 output ({_LLM_REVIEW_FORMAT}): `{preflight['paths']['findings_output']}`\n"
        f"- Stage state JSON: `{preflight['paths']['state']}`\n\n"
        "## Hard Gates\n\n"
        "1. Do not perform the review inline from these prompts or this runbook.\n"
        "2. If diff source is not `pr-target` or `current-pr`, stop and rerun `agentpack review --pr <number>`.\n"
        "3. If you cannot write the Stage 1 output file at the declared path, stop and report blocked.\n"
        "4. After Stage 1, run `agentpack review --check`; do not start Stage 2 until it validates Stage 1.\n"
        "5. After Stage 2, run `agentpack review --check`; do not produce a final summary unless it validates Stage 2.\n\n"
        "## Workflow\n\n"
        f"1. Read the Stage 1 prompt file completely and produce the understanding {_LLM_REVIEW_FORMAT} at the declared output path.\n"
        f"2. Run `agentpack review --check` and confirm the understanding {_LLM_REVIEW_FORMAT} file exists and follows the declared schema before moving on.\n"
        f"3. Read the Stage 2 prompt file completely and produce the findings {_LLM_REVIEW_FORMAT} at the declared output path.\n"
        f"4. Run `agentpack review --check` and confirm the findings {_LLM_REVIEW_FORMAT} file exists and follows the declared schema before reporting back.\n"
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
    lines = [_load_review_template(template_name)]
    lines.extend(
        [
            "",
            "## AgentPack Run Inputs",
            "",
            f"- Review run id: {preflight['review']['run_id']}",
            f"- Review mode: {preflight['review'].get('mode', 'fresh')}",
            f"- Preflight JSON: {preflight['paths']['preflight']}",
            f"- Head SHA: {preflight['git']['head_sha']}",
            f"- Diff range: {preflight['diff']['range']}",
            f"- Diff source: {preflight['diff']['source']}",
            f"- Review target: PR #{preflight['review'].get('target', {}).get('number')}"
            if preflight["review"].get("target", {}).get("number")
            else "- Review target: current branch/local fallback",
            f"- Output path: {_rel_to_root(abs_output, root)}",
            f"- Structured output format: {_LLM_REVIEW_FORMAT}",
        ]
    )
    context_pack = preflight.get("context_pack") if isinstance(preflight.get("context_pack"), dict) else {}
    if context_pack.get("path"):
        lines.append(f"- Broad AgentPack context: {context_pack['path']}")
    if prior_path is not None:
        lines.append(f"- Input path: {_rel_to_root(prior_path.resolve(), root)}")
    lines.extend(
        [
            "",
            "## Execution Gates",
            "",
            "- Do not answer inline from this stage prompt.",
            "- Write the required TOON artifact to the declared output path and nothing else.",
            "- If you cannot write the file or validate that it exists, stop and report blocked.",
            "- Run `agentpack review --check` after writing this artifact before continuing.",
        ]
    )
    if prior_path is not None:
        lines.append("- Do not continue until the declared input TOON exists and has been read from disk.")
    if preflight["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in preflight["warnings"])
    lines.extend(["", "Reviewer context:", preflight["review_context"] or "(none)"])
    return "\n".join(lines).rstrip() + "\n"


def _build_review_context_pack(
    root: Path,
    review_context: str,
    diff_info: dict[str, Any],
    outputs: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    target_label = diff_info.get("target_label") or "current PR"
    task = f"review {target_label} with broad repo context"
    if review_context:
        task = f"{task}: {review_context[:200]}"
    try:
        result = PackService().run(PackRequest(
            root=root,
            agent="generic",
            task=task,
            mode="deep",
            budget=0,
            since=diff_info.get("base_ref") or None,
            refresh=False,
            task_source="review",
            output_path=outputs["run_dir"] / "context.md",
            write_canonical=False,
        ))
    except Exception as exc:
        warnings.append(f"Could not build broad AgentPack context for review: {exc}")
        return {"path": "", "tokens": 0, "selected_files": 0, "broad_context": False}
    return {
        "path": _rel_to_root(result.out_path, root),
        "tokens": result.packed_tokens,
        "selected_files": len(result.pack.selected_files),
        "broad_context": result.pack.broad_context is not None,
    }


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


def _gh_pr_metadata(root: Path, target: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if shutil.which("gh") is None:
        return None
    target_arg = _target_cli_arg(target)
    args = ["gh", "pr", "view"]
    if target_arg:
        args.append(target_arg)
    args.extend([
        "--json",
        "number,title,url,baseRefName,headRefName",
    ])
    result = subprocess.run(
        args,
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


def _diff_base(
    root: Path,
    pr: dict[str, Any] | None,
    *,
    target: dict[str, Any] | None = None,
    allow_local_fallback: bool = False,
) -> dict[str, str]:
    if pr:
        number = pr.get("number") or (target or {}).get("number")
        base_name = str(pr.get("base_ref") or "").strip()
        if number and base_name:
            fetched = _fetch_pr_refs(root, int(number), base_name)
            if fetched["ok"]:
                base_ref = f"origin/{base_name}"
                head_ref = f"origin/pr/{number}"
                return {
                    "base_ref": base_ref,
                    "head_ref": head_ref,
                    "head_sha": _rev_parse(root, head_ref),
                    "range": f"{base_ref}...{head_ref}",
                    "source": "pr-target" if target else "current-pr",
                    "target_label": f"PR #{number}",
                }
            if not allow_local_fallback:
                raise _ReviewPreflightError(
                    f"could not fetch PR #{number} refs ({fetched['error']}); "
                    "rerun with network/GitHub access or pass --allow-local-fallback explicitly"
                )
        elif not allow_local_fallback:
            raise _ReviewPreflightError("PR metadata missing number/base branch; pass --pr <number> or --allow-local-fallback")
        return _local_diff_base(root, pr, fallback_reason=f"PR ref fetch unavailable for #{number or '?'}")

    if not allow_local_fallback:
        target_hint = _target_cli_arg(target)
        if target_hint:
            raise _ReviewPreflightError(
                f"gh PR metadata unavailable for {target_hint}; review diff not trusted. "
                "Fix gh auth/network or pass --allow-local-fallback explicitly."
            )
        raise _ReviewPreflightError(
            "gh PR metadata unavailable; pass --pr <number-or-url> so review can bind to the requested PR, "
            "or pass --allow-local-fallback explicitly for local branch review"
        )
    return _local_diff_base(root, pr, fallback_reason="gh PR metadata unavailable")


def _local_diff_base(root: Path, pr: dict[str, Any] | None, *, fallback_reason: str) -> dict[str, str]:
    base_name = (pr or {}).get("base_ref", "")
    for candidate in _base_candidates(base_name):
        if _git_ref_exists(root, candidate):
            return {
                "base_ref": candidate,
                "head_ref": "HEAD",
                "head_sha": git_core.current_sha(root) or "",
                "range": f"{candidate}...HEAD",
                "source": "local-fallback",
                "fallback_reason": fallback_reason,
                "target_label": "local branch",
            }
    if _git_ref_exists(root, "HEAD~1"):
        return {
            "base_ref": "HEAD~1",
            "head_ref": "HEAD",
            "head_sha": git_core.current_sha(root) or "",
            "range": "HEAD~1..HEAD",
            "source": "local-fallback",
            "fallback_reason": fallback_reason,
            "target_label": "local branch",
        }
    return {
        "base_ref": "HEAD",
        "head_ref": "HEAD",
        "head_sha": git_core.current_sha(root) or "",
        "range": "HEAD",
        "source": "local-fallback",
        "fallback_reason": fallback_reason,
        "target_label": "local branch",
    }


def _fetch_pr_refs(root: Path, number: int, base_name: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "git",
            "fetch",
            "--quiet",
            "origin",
            f"+refs/heads/{base_name}:refs/remotes/origin/{base_name}",
            f"+refs/pull/{number}/head:refs/remotes/origin/pr/{number}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return {"ok": True, "error": ""}
    return {"ok": False, "error": (result.stderr or result.stdout or f"git fetch exited {result.returncode}").strip()}


def _rev_parse(root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


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


def _warnings(
    root: Path,
    pr: dict[str, Any] | None,
    diff_info: dict[str, str],
    changed_paths: list[str],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    info: list[str] = []
    dirty = sorted(git_core.dirty_files(root))
    dirty_overlap = sorted(set(dirty) & set(changed_paths))
    if dirty_overlap:
        warnings.append(
            f"dirty tree overlaps review diff ({len(dirty_overlap)} path(s)); review the fetched PR head, not local edits"
        )
    elif dirty:
        info.append(f"dirty tree has {len(dirty)} unrelated path(s); no overlap with review diff")
    warnings.extend(_incomplete_review_run_warnings(root))
    if not pr:
        warnings.append("gh PR metadata unavailable; review is using local git context only")
    if diff_info["source"] == "local-fallback":
        warnings.append(f"diff fell back to local range {diff_info['range']}: {diff_info.get('fallback_reason', 'unknown reason')}")
    if not changed_paths:
        warnings.append("no changed files detected for the selected diff range")
    generated = [path for path in changed_paths if path.startswith(".agentpack/")]
    if generated:
        warnings.append("generated AgentPack artifacts are in the diff; keep them low priority unless the change is about distribution or docs")
    return warnings, info


def _incomplete_review_run_warnings(root: Path) -> list[str]:
    branch = git_core.current_branch(root) or "HEAD"
    branch_prefix = branch.replace("/", "-")
    branch_dir = root / _REVIEW_RUNS_DIR / branch_prefix
    if not branch_dir.exists():
        return []
    warnings: list[str] = []
    for run_dir in sorted((path for path in branch_dir.iterdir() if path.is_dir()), reverse=True):
        understanding = run_dir / "understanding.toon"
        findings = run_dir / "findings.toon"
        if understanding.exists():
            try:
                _validate_review_artifact(understanding, kind="understanding")
            except ValueError as exc:
                warnings.append(f"invalid understanding TOON in {run_dir.name}: {exc}")
                break
        if findings.exists():
            try:
                _validate_review_artifact(findings, kind="findings")
            except ValueError as exc:
                warnings.append(f"invalid findings TOON in {run_dir.name}: {exc}")
                break
        if understanding.exists() and not findings.exists():
            warnings.append(
                f"incomplete previous review run {run_dir.name}; start fresh by default or resume with `agentpack review --resume {run_dir.name}`"
            )
            break
    return warnings


def _review_state(root: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    understanding = root / preflight["paths"]["understanding_output"]
    findings = root / preflight["paths"]["findings_output"]
    status = "awaiting_understanding"
    try:
        if understanding.exists():
            _validate_review_artifact(understanding, kind="understanding")
            status = "awaiting_findings"
        if findings.exists():
            _validate_review_artifact(findings, kind="findings")
            status = "complete"
    except ValueError:
        status = "blocked_invalid_artifact"
    return {
        "generated_at": _now_iso(),
        "run_id": preflight["review"]["run_id"],
        "status": status,
        "preflight": preflight["paths"]["preflight"],
        "understanding_output": preflight["paths"]["understanding_output"],
        "findings_output": preflight["paths"]["findings_output"],
        "check_command": "agentpack review --check",
    }


def _check_active_review(root: Path) -> None:
    if not (root / _PREFLIGHT_PATH).exists():
        console.print("[red]No active review preflight found.[/] Run `agentpack review --pr <number>` first.")
        raise typer.Exit(1)
    try:
        preflight = json.loads((root / _PREFLIGHT_PATH).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Active review preflight is invalid JSON:[/] {exc}")
        raise typer.Exit(1) from exc

    understanding = root / preflight["paths"]["understanding_output"]
    findings = root / preflight["paths"]["findings_output"]
    state_path = root / preflight["paths"].get("state", _STATE_PATH)

    if not understanding.exists():
        state = _review_state(root, preflight)
        _write_review_state(root, preflight, state)
        console.print(f"[red]Stage 1 artifact missing:[/] {preflight['paths']['understanding_output']}")
        raise typer.Exit(1)
    try:
        _validate_review_artifact(understanding, kind="understanding")
    except ValueError as exc:
        state = _review_state(root, preflight)
        _write_review_state(root, preflight, state)
        console.print(f"[red]Stage 1 artifact invalid:[/] {exc}")
        raise typer.Exit(1) from exc

    if not findings.exists():
        state = _review_state(root, preflight)
        _write_review_state(root, preflight, state)
        console.print("[green]✓[/] Stage 1 valid. Proceed to Stage 2 judge prompt.")
        console.print(f"State: [bold]{_rel_to_root(state_path, root)}[/]")
        return
    try:
        _validate_review_artifact(findings, kind="findings")
    except ValueError as exc:
        state = _review_state(root, preflight)
        _write_review_state(root, preflight, state)
        console.print(f"[red]Stage 2 artifact invalid:[/] {exc}")
        raise typer.Exit(1) from exc

    state = _review_state(root, preflight)
    _write_review_state(root, preflight, state)
    console.print("[green]✓[/] Stage 2 valid. Review artifacts complete; final summary is unblocked.")
    console.print(f"State: [bold]{_rel_to_root(state_path, root)}[/]")


def _write_review_state(root: Path, preflight: dict[str, Any], state: dict[str, Any]) -> None:
    targets = [root / _STATE_PATH]
    if preflight.get("paths", {}).get("state"):
        targets.append(root / preflight["paths"]["state"])
    content = json.dumps(state, indent=2) + "\n"
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content)


def _validate_review_artifact(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        payload = load_toon(path)
    except (OSError, ToonParseError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} is not valid TOON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must decode to an object")
    if kind == "understanding":
        required = ("intent", "change_units", "open_questions")
    else:
        required = ("findings", "coverage")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"{path.name} missing required key(s): {', '.join(missing)}")
    root = _validation_root(path)
    citation_validation = (
        _validate_understanding_citations(root, payload)
        if kind == "understanding"
        else _validate_findings_citations(root, payload)
    )
    if citation_validation.invalid or citation_validation.missing:
        details = [*citation_validation.invalid[:5], *citation_validation.missing[:5]]
        suffix = "; ".join(details) if details else "missing citation"
        report_path = _write_review_validation_report(path, kind, citation_validation)
        report_note = f"; full report: {report_path.name}" if report_path else ""
        raise ValueError(f"{path.name} has invalid or missing citations: {suffix}{report_note}")
    return payload


def _write_review_validation_report(path: Path, kind: str, validation: CitationValidation) -> Path | None:
    try:
        report_path = path.with_name(f"{kind}-validation-errors.json")
        payload = {
            "artifact": path.name,
            "kind": kind,
            "invalid": validation.invalid,
            "missing": validation.missing,
            "valid_count": len(validation.valid),
        }
        report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return report_path
    except OSError:
        return None


def _validate_findings_citations(root: Path, payload: dict[str, Any]) -> CitationValidation:
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        return CitationValidation(valid=[], invalid=["findings must be a list"], missing=[])
    citations: list[Citation] = []
    invalid: list[str] = []
    missing: list[str] = []
    semantic_judge = _semantic_support_judge()
    for index, finding in enumerate(raw_findings, start=1):
        if not isinstance(finding, dict):
            invalid.append(f"finding {index}: not an object")
            continue
        location = parse_location(str(finding.get("location") or ""))
        if location is None:
            missing.append(f"finding {index}: missing valid location path:line")
        else:
            location.claim_id = f"finding:{index}:location"
            citations.append(location)
        evidence_citations = extract_location_citations(finding.get("evidence"))
        if not evidence_citations:
            missing.append(f"finding {index}: missing evidence path:line")
        for citation in evidence_citations:
            citation.claim_id = f"finding:{index}:evidence"
            citations.append(citation)
        invalid.extend(
            validate_claim_support(
                root,
                finding.get("evidence"),
                evidence_citations,
                label=f"finding {index}.evidence",
                semantic_judge=semantic_judge,
            )
        )
    validation = validate_citations(root, citations)
    return CitationValidation(valid=validation.valid, invalid=[*invalid, *validation.invalid], missing=[*missing, *validation.missing])


def _validate_understanding_citations(root: Path, payload: dict[str, Any]) -> CitationValidation:
    raw_units = payload.get("change_units")
    if not isinstance(raw_units, list):
        return CitationValidation(valid=[], invalid=["change_units must be a list"], missing=[])
    citations: list[Citation] = []
    invalid: list[str] = []
    missing: list[str] = []
    semantic_judge = _semantic_support_judge()
    for unit_index, unit in enumerate(raw_units, start=1):
        if not isinstance(unit, dict):
            invalid.append(f"change_unit {unit_index}: not an object")
            continue
        for field in ("code", "referenced_symbols", "callers", "contracts_touched", "local_convention_refs"):
            field_citations = extract_location_citations(unit.get(field))
            if field in {"referenced_symbols", "callers", "contracts_touched"} and unit.get(field) and not field_citations:
                missing.append(f"change_unit {unit_index}.{field}: missing path:line")
            for citation in field_citations:
                citation.claim_id = f"change_unit:{unit_index}:{field}"
                citations.append(citation)
            if field in {"referenced_symbols", "callers", "local_convention_refs"}:
                invalid.extend(
                    validate_claim_support(
                        root,
                        unit.get(field),
                        field_citations,
                        label=f"change_unit {unit_index}.{field}",
                        semantic_judge=semantic_judge,
                    )
                )
    validation = validate_citations(root, citations)
    return CitationValidation(valid=validation.valid, invalid=[*invalid, *validation.invalid], missing=[*missing, *validation.missing])


def _semantic_support_judge():
    command = os.environ.get("AGENTPACK_CITATION_SEMANTIC_COMMAND", "").strip()
    if not command:
        return None
    try:
        return semantic_support_command_judge(command)
    except ValueError:
        return lambda _payload: "semantic support command is empty"


def _validation_root(path: Path) -> Path:
    for candidate in (path.parent, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    for candidate in (path.parent, *path.parents):
        if candidate.name == ".agentpack":
            return candidate.parent
    return Path.cwd()


def _rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
