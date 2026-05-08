from __future__ import annotations

import json
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
) -> None:
    meta = {
        "context_path": context_path,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_root_hash": snapshot_root_hash,
        "task": task,
        "agent": agent,
        "mode": mode,
        "budget": budget,
        "token_estimate": token_estimate,
    }
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


def select_files(
    files: list[FileInfo],
    scored: list[tuple[FileInfo, float, list[str]]],
    changed_paths: set[str],
    summaries: dict[str, Any],
    mode: Mode,
    budget: int,
    max_file_tokens: int,
    keywords: set[str] | None = None,
) -> tuple[list[SelectedFile], list[Receipt]]:
    opts = _MODE_WEIGHTS[mode]
    selected: list[SelectedFile] = []
    receipts: list[Receipt] = []
    tokens_used = 0
    kw = keywords or set()

    for fi, score, reasons in sorted(scored, key=lambda x: -x[1]):
        if fi.ignored or fi.binary:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="ignored or binary"))
            continue

        if score <= 0:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="score too low"))
            continue

        is_changed = fi.path in changed_paths
        summary_data = summaries.get(fi.path)

        # Determine inclusion mode
        if is_changed and fi.estimated_tokens <= max_file_tokens:
            mode_str: Literal["full", "symbols", "summary"] = "full"
            content = fi.content if fi.content is not None else (
                fi.abs_path.read_text(errors="replace") if fi.abs_path.exists() else None
            )
            tok = fi.estimated_tokens
        elif is_changed or (opts["extra_full"] and fi.estimated_tokens <= max_file_tokens):
            mode_str = "symbols"
            content = None
            tok = min(fi.estimated_tokens, max_file_tokens // 2)
        elif summary_data:
            mode_str = "summary"
            content = None
            tok = estimate_tokens(summary_data.get("summary", ""))
        else:
            mode_str = "summary"
            content = None
            tok = min(fi.estimated_tokens, 200)

        if tokens_used + tok > budget:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="budget exhausted"))
            continue

        tokens_used += tok

        # Build symbol list
        syms: list[Symbol] = []
        if summary_data and mode_str in ("symbols", "summary"):
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
        materialized = content if mode_str == "full" else sym_body_content
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
