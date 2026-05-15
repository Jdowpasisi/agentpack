from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agentpack.core.models import (
    FileInfo,
    Receipt,
    SelectedFile,
    Symbol,
)
from agentpack.core.redactor import redact_secrets
from agentpack.core.token_estimator import estimate_tokens


Mode = Literal["minimal", "balanced", "deep"]

_MODE_WEIGHTS: dict[str, dict[str, bool]] = {
    "minimal": {
        "include_unchanged_deps": False,
        "include_rev_deps": False,
        "include_tests": False,
        "include_docs": False,
        "extra_full": False,
    },
    "balanced": {
        "include_unchanged_deps": True,
        "include_rev_deps": True,
        "include_tests": True,
        "include_docs": False,
        "extra_full": False,
    },
    "deep": {
        "include_unchanged_deps": True,
        "include_rev_deps": True,
        "include_tests": True,
        "include_docs": True,
        "extra_full": True,
    },
}


def _metadata_path(root: Path) -> Path:
    return root / ".agentpack" / "pack_metadata.json"


def save_pack_metadata(
    root: Path,
    context_path: str,
    snapshot_root_hash: str,
    task: str,
    agent: str,
    mode: str,
    budget: int,
    token_estimate: int = 0,
    freshness: dict[str, Any] | None = None,
    freshness_warnings: list[str] | None = None,
    selected_files: list[dict[str, Any]] | None = None,
) -> None:
    generated_at = (
        freshness.get("generated_at")
        if freshness and freshness.get("generated_at")
        else datetime.now(timezone.utc).isoformat()
    )
    meta = {
        "context_path": context_path,
        "generated_at": generated_at,
        "snapshot_root_hash": snapshot_root_hash,
        "task": task,
        "agent": agent,
        "mode": mode,
        "budget": budget,
        "token_estimate": token_estimate,
        "selected_files_meta": selected_files or [],
        "freshness": freshness or {},
        "freshness_warnings": freshness_warnings or [],
    }
    if freshness:
        for key in ("git_sha", "git_branch", "task_source", "changed_files_source", "task_class"):
            if key in freshness:
                meta[key] = freshness[key]
    _metadata_path(root).write_text(json.dumps(meta, indent=2))


def load_pack_metadata(root: Path) -> dict[str, Any] | None:
    path = _metadata_path(root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _extract_relevant_symbol_bodies(
    fi: FileInfo,
    syms: list[Symbol],
    keywords: set[str],
    budget_remaining: int,
) -> tuple[str | None, int]:
    """Assemble symbol bodies from Symbol.body (captured at extraction time — no file re-read)."""
    from agentpack.analysis.symbols import filter_symbols_by_keywords

    relevant = filter_symbols_by_keywords(syms, keywords) if keywords else syms[:5]
    if not relevant:
        return None, 0

    parts: list[str] = []
    tokens_used = 0
    for sym in relevant:
        body = sym.body
        if body:
            tok = estimate_tokens(body)
            if tokens_used + tok <= budget_remaining:
                parts.append(body)
                tokens_used += tok
            elif sym.signature:
                sig_tok = estimate_tokens(sym.signature)
                if tokens_used + sig_tok <= budget_remaining:
                    parts.append(sym.signature)
                    tokens_used += sig_tok
        elif sym.signature:
            sig_tok = estimate_tokens(sym.signature)
            if tokens_used + sig_tok <= budget_remaining:
                parts.append(sym.signature)
                tokens_used += sig_tok

    return "\n\n".join(parts) if parts else None, tokens_used


def _has_task_signal(reasons: list[str]) -> bool:
    """Return True when a file matched the task beyond generic dirtiness."""
    weak_prefixes = (
        "modified",
        "staged",
        "recently modified",
        "high churn",
    )
    return any(not reason.startswith(weak_prefixes) for reason in reasons)


def _git_diff_for_file(fi: FileInfo, max_tokens: int, keywords: set[str] | None = None) -> tuple[str | None, int]:
    """Return a compact git diff for one file when available."""
    root = _find_git_root(fi.abs_path)
    if root is None:
        return None, 0
    rel = fi.path
    pieces: list[str] = []
    for args in (["git", "diff", "--", rel], ["git", "diff", "--cached", "--", rel]):
        try:
            result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            pieces.append(result.stdout.strip())
    diff_text = "\n".join(pieces).strip()
    if not diff_text:
        return None, 0
    content = _select_diff_hunks(diff_text, max_tokens=max_tokens, keywords=keywords or set())
    return content, estimate_tokens(content)


def _select_diff_hunks(diff_text: str, max_tokens: int, keywords: set[str]) -> str:
    """Keep diff headers and the most task-relevant hunks under budget."""
    lines = diff_text.splitlines()
    if not lines:
        return ""
    header: list[str] = []
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("@@"):
            current = [line]
            hunks.append(current)
        elif current is None:
            header.append(line)
        else:
            current.append(line)

    if not hunks:
        return _truncate_lines(lines, max_tokens)

    keyword_lc = {kw.lower() for kw in keywords if len(kw) >= 3}

    def hunk_score(item: tuple[int, list[str]]) -> tuple[int, int]:
        index, hunk = item
        text = "\n".join(hunk).lower()
        hits = sum(1 for kw in keyword_lc if kw in text)
        changed_lines = sum(1 for line in hunk if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        return hits * 100 + changed_lines, -index

    ordered = sorted(enumerate(hunks), key=hunk_score, reverse=True)
    kept_hunks: list[tuple[int, list[str]]] = []
    kept_text = "\n".join(header)
    for index, hunk in ordered:
        candidate_parts = [kept_text] if kept_text else []
        candidate_parts.extend("\n".join(existing) for _i, existing in kept_hunks)
        candidate_parts.append("\n".join(hunk))
        candidate = "\n".join(part for part in candidate_parts if part)
        if estimate_tokens(candidate) <= max_tokens:
            kept_hunks.append((index, hunk))
            kept_text = "\n".join(header)
        elif not kept_hunks:
            truncated = _truncate_lines([*header, *hunk], max_tokens)
            return truncated

    omitted = len(hunks) - len(kept_hunks)
    kept_hunks.sort(key=lambda item: item[0])
    output: list[str] = [*header]
    if omitted > 0:
        output.append(f"... {omitted} less relevant diff hunk(s) omitted by AgentPack ...")
    for _index, hunk in kept_hunks:
        output.extend(hunk)
    return "\n".join(output)


def _truncate_lines(lines: list[str], max_tokens: int) -> str:
    kept: list[str] = []
    tokens = 0
    for line in lines:
        line_tokens = estimate_tokens(line)
        if kept and tokens + line_tokens > max_tokens:
            kept.append("... diff truncated by AgentPack budget ...")
            break
        kept.append(line)
        tokens += line_tokens
    return "\n".join(kept)


def _find_git_root(path: Path) -> Path | None:
    cur = path if path.is_dir() else path.parent
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _skeleton_content(fi: FileInfo, summary_data: dict[str, Any] | None) -> tuple[str | None, int]:
    """Build a compact interface view from imports and signatures."""
    if not summary_data:
        return None, 0
    lines: list[str] = []
    imports = summary_data.get("imports") or []
    if imports:
        lines.append("# imports")
        lines.extend(f"- {item}" for item in imports[:20])
    raw_symbols = summary_data.get("symbols") or []
    symbol_lines: list[str] = []
    for raw in raw_symbols[:40]:
        try:
            sym = Symbol(**raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
        if sym.signature:
            symbol_lines.append(sym.signature)
        else:
            symbol_lines.append(f"{sym.kind} {sym.name}")
    if symbol_lines:
        if lines:
            lines.append("")
        lines.append("# interface")
        lines.extend(symbol_lines)
    if not lines and summary_data.get("summary"):
        lines.append(str(summary_data["summary"]))
    content = "\n".join(lines).strip()
    return (content, estimate_tokens(content)) if content else (None, 0)


def _summary_tokens(summary_data: dict[str, Any] | None, fallback: int) -> int:
    if not summary_data:
        return fallback
    parts = [str(summary_data.get("summary", ""))]
    for raw in summary_data.get("symbols") or []:
        try:
            sym = Symbol(**raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
        if sym.signature:
            parts.append(sym.signature)
    return estimate_tokens("\n".join(part for part in parts if part))


def _selection_priority(
    item: tuple[FileInfo, float, list[str]],
    changed_paths: set[str],
    max_file_tokens: int,
) -> tuple[int, int, float, float]:
    """Hybrid rank: changed/task-relevant first, then score with a token-value nudge."""
    fi, score, reasons = item
    changed_priority = 1 if fi.path in changed_paths else 0
    signal_priority = 1 if _has_task_signal(reasons) else 0
    role_bonus = 0.0
    if any(
        ("test for high-scoring" in reason and "docs/" not in reason and "examples/" not in reason)
        or "related test" in reason
        for reason in reasons
    ):
        role_bonus += 30.0
    if any("config file" in reason for reason in reasons):
        role_bonus += 25.0
    rough_tokens = max(1, min(fi.estimated_tokens, max_file_tokens))
    value_bonus = min(60.0, (score / rough_tokens) * 120.0)
    return changed_priority, signal_priority, score + role_bonus + value_bonus, score


def select_files(
    files: list[FileInfo],
    scored: list[tuple[FileInfo, float, list[str]]],
    changed_paths: set[str],
    summaries: dict[str, Any],
    mode: Mode,
    budget: int,
    max_file_tokens: int,
    keywords: set[str] | None = None,
    min_summary_score: float = 0,
    max_summary_files: int = 0,
) -> tuple[list[SelectedFile], list[Receipt]]:
    opts = _MODE_WEIGHTS[mode]
    selected: list[SelectedFile] = []
    receipts: list[Receipt] = []
    tokens_used = 0
    summaries_used = 0
    kw = keywords or set()
    budget_pressure = budget < 12000 or len(changed_paths) > 5

    ordered = sorted(scored, key=lambda item: _selection_priority(item, changed_paths, max_file_tokens), reverse=True)
    for fi, score, reasons in ordered:
        if fi.ignored or fi.binary:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="ignored or binary"))
            continue

        if score <= 0:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="score too low"))
            continue

        is_changed = fi.path in changed_paths
        summary_data = summaries.get(fi.path)
        has_task_signal = _has_task_signal(reasons)
        will_be_summary = not is_changed and not (
            opts["extra_full"] and fi.estimated_tokens <= max_file_tokens
        )
        if will_be_summary and score < min_summary_score:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="summary score below floor"))
            continue

        # Determine inclusion mode. Changed files are not all equal: tiny or
        # task-matching files still get full source, while large unrelated dirty
        # files are compressed before they can consume the whole budget.
        mode_str: Literal["full", "diff", "symbols", "skeleton", "summary"]
        content: str | None = None
        diff_content: str | None = None
        skeleton: str | None = None
        skeleton_tokens = 0

        if summary_data:
            skeleton, skeleton_tokens = _skeleton_content(fi, summary_data)

        if is_changed:
            small_changed = fi.estimated_tokens <= min(600, max_file_tokens)
            should_full = fi.estimated_tokens <= max_file_tokens and (
                small_changed or (has_task_signal and not budget_pressure)
            )
            if should_full:
                mode_str = "full"
                content = fi.content if fi.content is not None else (
                    fi.abs_path.read_text(errors="replace") if fi.abs_path.exists() else None
                )
                tok = fi.estimated_tokens
            else:
                diff_content, diff_tokens = _git_diff_for_file(
                    fi,
                    max(200, min(max_file_tokens // 2, budget // 4)),
                    keywords=kw,
                )
                if diff_content:
                    mode_str = "diff"
                    content = diff_content
                    tok = diff_tokens
                    reasons = reasons + ["compressed changed file as diff"]
                elif has_task_signal:
                    mode_str = "symbols"
                    tok = min(fi.estimated_tokens, max_file_tokens // 2)
                elif skeleton:
                    mode_str = "skeleton"
                    content = skeleton
                    tok = skeleton_tokens
                    reasons = reasons + ["dirty file compressed to skeleton"]
                elif summary_data:
                    mode_str = "summary"
                    tok = _summary_tokens(summary_data, min(fi.estimated_tokens, 200))
                    reasons = reasons + ["dirty file compressed to summary"]
                else:
                    mode_str = "summary"
                    tok = min(fi.estimated_tokens, 200)
                    reasons = reasons + ["dirty file compressed to summary"]
        elif fi.estimated_tokens <= max_file_tokens and score > 0 and _has_redactable_secret(fi):
            mode_str = "full"
            content = fi.content if fi.content is not None else (
                fi.abs_path.read_text(errors="replace") if fi.abs_path.exists() else None
            )
            tok = fi.estimated_tokens
            reasons = reasons + ["full file included for secret redaction"]
        elif opts["extra_full"] and fi.estimated_tokens <= max_file_tokens and score >= 120:
            mode_str = "full"
            content = fi.content if fi.content is not None else (
                fi.abs_path.read_text(errors="replace") if fi.abs_path.exists() else None
            )
            tok = fi.estimated_tokens
        elif summary_data and skeleton and score >= 160 and mode != "minimal":
            mode_str = "skeleton"
            content = skeleton
            tok = skeleton_tokens
        elif summary_data:
            mode_str = "summary"
            tok = _summary_tokens(summary_data, min(fi.estimated_tokens, 200))
        else:
            mode_str = "summary"
            tok = min(fi.estimated_tokens, 200)

        if tokens_used + tok > budget:
            fallback = _budget_fallback(
                mode_str=mode_str,
                fi=fi,
                summary_data=summary_data,
                skeleton=skeleton,
                skeleton_tokens=skeleton_tokens,
                current_tokens=tokens_used,
                budget=budget,
                max_file_tokens=max_file_tokens,
            )
            if fallback is not None:
                mode_str, content, tok, why = fallback
                reasons = reasons + [why]

        if mode_str == "summary" and max_summary_files < 0:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="summaries disabled by precision guard"))
            continue

        if mode_str == "summary" and max_summary_files > 0 and summaries_used >= max_summary_files:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="summary cap reached"))
            continue

        if tokens_used + tok > budget:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="budget exhausted"))
            continue

        tokens_used += tok
        if mode_str == "summary":
            summaries_used += 1

        # Build symbol list
        syms: list[Symbol] = []
        if summary_data and mode_str in ("symbols", "summary", "skeleton"):
            raw_syms = summary_data.get("symbols", [])
            for s in raw_syms:
                try:
                    syms.append(Symbol(**s) if isinstance(s, dict) else s)
                except Exception as exc:
                    import warnings
                    warnings.warn(f"skipping malformed symbol in {fi.path}: {exc}", stacklevel=2)

        # Symbol body extraction for "symbols" mode
        sym_body_content: str | None = None
        if mode_str == "symbols" and syms and fi.abs_path.exists():
            budget_remaining = budget - tokens_used
            sym_body_content, extra_tok = _extract_relevant_symbol_bodies(
                fi, syms, kw, min(budget_remaining, max_file_tokens // 2)
            )
            if extra_tok > 0 and tokens_used + extra_tok <= budget:
                tokens_used += extra_tok

        # Redact secrets at materialization — before content reaches any renderer or adapter
        materialized = content if mode_str in ("full", "diff", "skeleton") else sym_body_content
        redaction_warnings: list[str] = []
        if materialized:
            materialized, redaction_warnings = redact_secrets(materialized, fi.path)

        selected.append(
            SelectedFile(
                path=fi.path,
                language=fi.language,
                score=score,
                include_mode=mode_str,
                reasons=reasons,
                content=materialized,
                summary=summary_data.get("summary") if summary_data else None,
                symbols=syms,
                redaction_warnings=redaction_warnings,
            )
        )

        action: Literal["included", "excluded", "summarized"] = (
            "included" if mode_str == "full" else "summarized"
        )
        receipts.append(
            Receipt(path=fi.path, action=action, reason=", ".join(reasons[:2]))
        )

    return selected, receipts



def _has_redactable_secret(fi: FileInfo) -> bool:
    text = fi.content
    if text is None and fi.abs_path.exists():
        try:
            text = fi.abs_path.read_text(errors="replace")
        except OSError:
            return False
    if not text:
        return False
    _redacted, warnings = redact_secrets(text, fi.path)
    return bool(warnings)


def _budget_fallback(
    *,
    mode_str: Literal["full", "diff", "symbols", "skeleton", "summary"],
    fi: FileInfo,
    summary_data: dict[str, Any] | None,
    skeleton: str | None,
    skeleton_tokens: int,
    current_tokens: int,
    budget: int,
    max_file_tokens: int,
) -> tuple[Literal["skeleton", "summary"], str | None, int, str] | None:
    """Downgrade high-value files instead of dropping them when budget is tight."""
    if mode_str == "summary":
        return None
    candidates: list[tuple[Literal["skeleton", "summary"], str | None, int, str]] = []
    if skeleton:
        candidates.append(("skeleton", skeleton, skeleton_tokens, "value optimizer downgraded to skeleton"))
    if summary_data:
        summary_tok = _summary_tokens(summary_data, min(fi.estimated_tokens, 200))
        candidates.append(("summary", None, summary_tok, "value optimizer downgraded to summary"))
    else:
        candidates.append(("summary", None, min(fi.estimated_tokens, min(200, max_file_tokens)), "value optimizer downgraded to summary"))

    for candidate in sorted(candidates, key=lambda item: item[2]):
        if current_tokens + candidate[2] <= budget:
            return candidate
    return None
