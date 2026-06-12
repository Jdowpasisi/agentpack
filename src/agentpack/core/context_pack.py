from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agentpack.core.models import (
    FileInfo,
    OmittedRelevantFile,
    Receipt,
    SelectedFile,
    Symbol,
)
from agentpack.core.redactor import redact_secrets
from agentpack.core.task_freshness import task_hash
from agentpack.core.token_estimator import estimate_tokens
from agentpack.core.modes import PackMode


Mode = PackMode

_MODE_WEIGHTS: dict[str, dict[str, bool]] = {
    "lite": {
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
    requested_mode: str | None = None,
    token_estimate: int = 0,
    freshness: dict[str, Any] | None = None,
    freshness_warnings: list[str] | None = None,
    selected_files: list[dict[str, Any]] | None = None,
    execution_state: dict[str, Any] | None = None,
    concurrent_context: dict[str, Any] | None = None,
    metadata_path: Path | None = None,
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
        "task_hash": task_hash(task),
        "agent": agent,
        "mode": mode,
        "requested_mode": requested_mode or mode,
        "budget": budget,
        "token_estimate": token_estimate,
        "selected_files_meta": selected_files or [],
        "freshness": freshness or {},
        "freshness_warnings": freshness_warnings or [],
        "execution_state": execution_state or {},
        "concurrent_context": concurrent_context or {},
    }
    if freshness:
        for key in ("git_sha", "git_branch", "task_source", "changed_files_source", "task_class"):
            if key in freshness:
                meta[key] = freshness[key]
    path = metadata_path or _metadata_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2))


def load_pack_metadata(root: Path, metadata_path: Path | None = None) -> dict[str, Any] | None:
    path = metadata_path or _metadata_path(root)
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
        "likely false positive",
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
    for label, field, limit in [
        ("# entrypoints", "entrypoints", 12),
        ("# external systems", "external_systems", 8),
    ]:
        values = summary_data.get(field) or []
        if values:
            if lines:
                lines.append("")
            lines.append(label)
            lines.extend(f"- {item}" for item in values[:limit])
    imports = summary_data.get("imports") or []
    if imports:
        if lines:
            lines.append("")
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
    summary = str(summary_data.get("summary") or "").strip()
    return estimate_tokens(summary) if summary else fallback


def _is_test_path(path: str) -> bool:
    path_lc = path.lower()
    name = Path(path_lc).name
    parts = {part.lower() for part in Path(path_lc).parts}
    return (
        path_lc.startswith(("tests/", "test/"))
        or "test" in parts
        or "/tests/" in path_lc
        or "__tests__/" in path_lc
        or "__test__/" in path_lc
        or name.startswith("test_")
        or name.endswith(("_test.go", "_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def _is_docs_path(path: str) -> bool:
    path_lc = path.lower()
    return path_lc.startswith(("docs/", "doc/")) or path_lc.endswith((".md", ".mdx", ".rst"))


def _is_example_or_playground_path(path: str) -> bool:
    path_parts = [part.lower() for part in Path(path).parts]
    parts = set(path_parts)
    sample_dir = bool(path_parts and path_parts[0] in {"sample", "samples"})
    return bool(
        parts
        & {
            "example",
            "examples",
            "fixture",
            "fixtures",
            "playground",
            "playgrounds",
            "template",
            "templates",
        }
    ) or sample_dir or any(part.startswith(("template-", "sample-")) for part in path_parts)


def _has_direct_source_evidence(reasons: list[str]) -> bool:
    return any(
        reason == "symbol keyword match"
        or reason.startswith((
            "matched domain:",
            "matched define:",
            "multi-token defines match",
            "matched call:",
            "matched entrypoint:",
            "keyword phrase match:",
        ))
        for reason in reasons
    )


def _content_keyword_hits(reasons: list[str]) -> int:
    hits = 0
    for reason in reasons:
        match = re.match(r"content keyword match \((\d+)\)", reason)
        if match:
            hits = max(hits, int(match.group(1)))
    return hits


_IGNORE_CONTROL_NAMES = {
    ".agentignore",
    ".cursorignore",
    ".dockerignore",
    ".eslintignore",
    ".gitignore",
    ".npmignore",
    ".prettierignore",
}

_IGNORE_TASK_TERMS = {
    "agentignore",
    "dockerignore",
    "eslintignore",
    "exclude",
    "excluded",
    "exclusion",
    "gitignore",
    "ignore",
    "ignored",
    "ignores",
    "ignoring",
    "npmignore",
    "prettierignore",
}


def _is_ignore_control_path(path: str) -> bool:
    return Path(path).name.lower() in _IGNORE_CONTROL_NAMES


def _has_ignore_task_evidence(reasons: list[str], keywords: set[str]) -> bool:
    if keywords & _IGNORE_TASK_TERMS:
        return True
    return any("ignore" in reason.lower() for reason in reasons)


def _has_actionable_compressed_evidence(reasons: list[str]) -> bool:
    content_hits = _content_keyword_hits(reasons)
    if any(
        reason.startswith((
            "caller of selected symbol",
            "direct content evidence",
            "direct dependency",
            "historically co-changed",
            "keyword phrase match:",
            "literal definition match:",
            "matched call:",
            "matched define:",
            "matched entrypoint:",
            "matched env read:",
            "matched external system:",
            "matched side effect:",
            "multi-token defines match",
            "quoted literal match:",
            "release/version metadata",
            "reverse dependency",
            "test for",
            "workspace match",
        ))
        or reason == "build/dependency metadata"
        or reason == "has related tests"
        for reason in reasons
    ):
        return True
    if "symbol keyword match" in reasons and content_hits >= 1:
        return True
    if any(reason.startswith("multi-term path match") for reason in reasons) and content_hits >= 1:
        return True
    return content_hits >= 4 and any(
        reason.startswith(("matched naming keyword:", "matched ranking keyword:", "matched role keyword:"))
        for reason in reasons
    )


def _weak_compressed_noise_reason(path: str, reasons: list[str], keywords: set[str]) -> str | None:
    if _is_ignore_control_path(path) and not _has_ignore_task_evidence(reasons, keywords):
        return "ignore-control file lacks ignore-task evidence"

    actionable = _has_actionable_compressed_evidence(reasons)
    if _is_test_path(path) and "explicit test task file" not in reasons and not actionable:
        return "test file lacks direct task evidence"

    broad_only = _is_source_path(path) and "implementation role match" in reasons and any(
        reason.startswith((
            "matched domain:",
            "matched naming keyword:",
            "matched ranking keyword:",
            "matched role keyword:",
        ))
        for reason in reasons
    )
    if broad_only and not actionable:
        return "broad family match lacks direct task evidence"

    return None


def _is_source_path(path: str) -> bool:
    if _is_test_path(path) or _is_docs_path(path) or _is_example_or_playground_path(path):
        return False
    if _is_lock_or_generated_path(path):
        return False
    suffix = Path(path).suffix.lower()
    if suffix not in {".go", ".rs", ".java", ".kt", ".py", ".ts", ".tsx", ".js", ".jsx"}:
        return False
    parts = {part.lower() for part in Path(path).parts}
    return (
        len(Path(path).parts) == 1
        or "src" in parts
        or "source" in parts
        or path.lower().startswith(("src/", "lib/", "pkg/", "cmd/", "packages/"))
    )


def _is_direct_source_candidate(path: str, reasons: list[str]) -> bool:
    if not _is_source_path(path):
        return False
    if "config file" in reasons:
        return False
    if not _has_direct_source_evidence(reasons):
        return False
    return True


def _is_root_go_source_candidate(path: str, reasons: list[str]) -> bool:
    return (
        len(Path(path).parts) == 1
        and Path(path).suffix.lower() == ".go"
        and _is_direct_source_candidate(path, reasons)
    )


def _selection_priority(
    item: tuple[FileInfo, float, list[str]],
    changed_paths: set[str],
    max_file_tokens: int,
    summaries: dict[str, Any] | None = None,
) -> tuple[int, int, float, float]:
    """Hybrid rank: changed/task-relevant first, then score with a token-value nudge."""
    fi, score, reasons = item
    changed_priority = 1 if fi.path in changed_paths else 0
    signal_priority = 1 if _has_task_signal(reasons) else 0
    role_bonus = 0.0
    explicit_test_task = any(reason == "explicit test task file" for reason in reasons)
    if _is_primary_release_metadata(fi.path, reasons):
        role_bonus += 180.0
    elif explicit_test_task:
        role_bonus += 45.0
    elif _is_root_go_source_candidate(fi.path, reasons):
        role_bonus += 230.0
    elif _is_direct_source_candidate(fi.path, reasons):
        role_bonus += 125.0
    elif any(
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


_RESERVED_BUCKET_ORDER = ("changed", "tests", "docs", "deps")

_CALL_TARGET_STOPWORDS = {
    "build",
    "check",
    "close",
    "create",
    "delete",
    "find",
    "get",
    "init",
    "list",
    "load",
    "main",
    "make",
    "open",
    "parse",
    "read",
    "render",
    "run",
    "save",
    "set",
    "test",
    "update",
    "write",
}


def classify_omission_risk(path: str, reasons: list[str], score: float) -> Literal["high", "medium", "low"]:
    path_lc = path.lower()
    reason_text = " ".join(reasons).lower()
    if (
        "reverse dependency" in reason_text
        or "caller" in reason_text
        or "related test" in reason_text
        or "test for" in reason_text
        or path_lc.startswith(("tests/", "test/"))
        or "/tests/" in path_lc
        or any(part in path_lc for part in ("route", "routes", "controller", "api/"))
        or any(part in path_lc for part in ("schema", "migration", "model", "models"))
    ):
        return "high"
    if (
        "direct dependency" in reason_text
        or "config" in reason_text
        or any(part in path_lc for part in ("config", ".env", "deploy", "settings"))
        or score > 150
    ):
        return "medium"
    return "low"


def enrich_call_site_scores(
    scored: list[tuple[FileInfo, float, list[str]]],
    selected: list[SelectedFile],
    summaries: dict[str, Any],
    changed_paths: set[str],
    *,
    boost: float = 90.0,
) -> tuple[list[tuple[FileInfo, float, list[str]]], int]:
    """Boost files whose cached calls reference symbols from selected source files."""
    targets = _selected_call_targets(selected, summaries, changed_paths)
    if not targets:
        return scored, 0

    selected_paths = {sf.path for sf in selected}
    expanded: list[tuple[FileInfo, float, list[str]]] = []
    changed_count = 0
    for fi, score, reasons in scored:
        if fi.path in selected_paths:
            expanded.append((fi, score, reasons))
            continue
        matched = _matched_called_symbols(summaries.get(fi.path), targets)
        if not matched:
            expanded.append((fi, score, reasons))
            continue
        caller_reasons = [f"caller of selected symbol `{name}`" for name in matched[:3]]
        new_reasons = [*reasons, *[reason for reason in caller_reasons if reason not in reasons]]
        expanded.append((fi, score + min(boost * len(matched), boost * 2), new_reasons))
        changed_count += 1

    return expanded, changed_count


def _selected_call_targets(
    selected: list[SelectedFile],
    summaries: dict[str, Any],
    changed_paths: set[str],
    *,
    limit: int = 40,
) -> dict[str, str]:
    targets: dict[str, str] = {}
    for sf in selected:
        if sf.include_mode not in ("full", "diff", "symbols") and sf.path not in changed_paths:
            continue
        summary_data = summaries.get(sf.path) or {}
        for raw_name in _summary_symbol_names(summary_data):
            base = _call_symbol_base(raw_name)
            if not base or base in targets:
                continue
            targets[base] = raw_name
            if len(targets) >= limit:
                return targets
    return targets


def _summary_symbol_names(summary_data: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for raw in summary_data.get("symbols") or []:
        name = raw.get("name") if isinstance(raw, dict) else getattr(raw, "name", None)
        if isinstance(name, str):
            names.append(name)
    for name in summary_data.get("defines") or []:
        if isinstance(name, str):
            names.append(name)
    return names


def _call_symbol_base(name: str) -> str | None:
    base = name.rsplit(".", 1)[-1].strip()
    if not base:
        return None
    base_lc = base.lower()
    if len(base_lc) < 4 or base_lc in _CALL_TARGET_STOPWORDS:
        return None
    if not re.search(r"[a-zA-Z]", base_lc):
        return None
    return base_lc


def _matched_called_symbols(summary_data: dict[str, Any] | None, targets: dict[str, str]) -> list[str]:
    if not summary_data:
        return []
    matched: list[str] = []
    for raw_call in summary_data.get("calls") or []:
        if not isinstance(raw_call, str):
            continue
        call_lc = raw_call.lower()
        call_base = _call_symbol_base(raw_call)
        for target_base, display_name in targets.items():
            if call_base == target_base or call_lc.endswith(f".{target_base}"):
                if display_name not in matched:
                    matched.append(display_name)
    return matched


def _selection_bucket(fi: FileInfo, reasons: list[str], changed_paths: set[str]) -> str:
    path = fi.path
    if path in changed_paths:
        return "changed"
    if _is_docs_path(path) or any(
        "knowledge/architecture doc" in reason for reason in reasons
    ):
        return "docs"
    if _is_test_path(path) or any(
        "test for" in reason or "related test" in reason for reason in reasons
    ):
        return "tests"
    if any(
        reason.startswith(("direct dependency", "reverse dependency", "cross-layer related"))
        or reason == "has related tests"
        for reason in reasons
    ):
        return "deps"
    return "other"


def _reserve_bucket_order(
    ordered: list[tuple[FileInfo, float, list[str]]],
    changed_paths: set[str],
    budget: int,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Seed top changed/test/doc/dependency files before normal rank order."""
    if not changed_paths or budget < 1000 or len(ordered) < 4:
        return ordered

    selected_indexes: set[int] = set()
    seeded: list[tuple[FileInfo, float, list[str]]] = []
    for bucket in _RESERVED_BUCKET_ORDER:
        for index, item in enumerate(ordered):
            if index in selected_indexes:
                continue
            fi, _score, reasons = item
            if _selection_bucket(fi, reasons, changed_paths) == bucket:
                seeded.append(item)
                selected_indexes.add(index)
                break

    if not seeded:
        return ordered
    seeded.extend(item for index, item in enumerate(ordered) if index not in selected_indexes)
    return seeded


_WEAK_SIGNAL_REASONS = {
    "broad-task weak-signal dampening",
    "no-live filename-only dampening",
    "broad-task meta-summary dampening",
}

_STRICT_SUMMARY_SUPPORT_PREFIXES = (
    "direct dependency of changed file",
    "reverse dependency",
    "historically co-changed",
    "has related tests",
    "test for",
    "release/version metadata",
    "build/dependency metadata",
    "secret redaction candidate",
    "matched domain:",
    "matched external system:",
    "matched env read:",
    "matched side effect:",
    "matched call:",
)

_EXPANSION_ONLY_SUPPORT_PREFIXES = (
    "recall neighbor",
    "workspace match",
    "large supported file",
    "second-pass recall neighbor",
)


def _is_weak_signal_candidate(reasons: list[str]) -> bool:
    return any(reason in _WEAK_SIGNAL_REASONS for reason in reasons)


def _has_strict_summary_support(reasons: list[str], path: str = "") -> bool:
    if any(reason.startswith(_STRICT_SUMMARY_SUPPORT_PREFIXES) for reason in reasons):
        return True
    has_phrase = any(reason.startswith("keyword phrase match:") for reason in reasons)
    has_config = "config file" in reasons
    has_impl_or_define = any(
        reason == "implementation role match"
        or reason.startswith(("matched define:", "multi-token defines match", "matched entrypoint:"))
        for reason in reasons
    )
    content_hits = _content_keyword_hits(reasons)
    path_obj = Path(path) if path else None
    has_root_go_source_path = (
        path_obj is not None
        and len(path_obj.parts) == 1
        and path_obj.suffix.lower() == ".go"
        and _is_source_path(path)
        and "config file" not in reasons
    )
    if has_root_go_source_path:
        has_scope_source_evidence = (
            "conventional scope path match" in reasons
            and any(
                reason == "filename keyword match" or reason.startswith("matched role keyword:")
                for reason in reasons
            )
        )
        has_content_source_evidence = content_hits >= 2 and (
            "implementation role match" in reasons
            or any(
                reason.startswith((
                    "direct content evidence",
                    "matched call:",
                    "keyword phrase match:",
                    "quoted literal match:",
                ))
                for reason in reasons
            )
        )
        if content_hits >= 5:
            return True
        if has_scope_source_evidence or has_content_source_evidence:
            return True
    if has_config and content_hits >= 2:
        return True
    if has_config and has_phrase and content_hits >= 1:
        return True
    has_direct_summary_field = any(
        reason.startswith((
            "matched define:",
            "multi-token defines match",
            "matched naming keyword:",
            "matched entrypoint:",
        ))
        for reason in reasons
    )
    has_symbol = "symbol keyword match" in reasons
    if has_direct_summary_field and (has_symbol or has_config or content_hits >= 1):
        return True
    has_expansion = any(reason.startswith(_EXPANSION_ONLY_SUPPORT_PREFIXES) for reason in reasons)
    if has_expansion:
        if has_phrase and has_impl_or_define and content_hits >= 1:
            return True
        return content_hits >= 2 and has_impl_or_define
    if has_phrase and has_impl_or_define and content_hits >= 1:
        return True
    return has_phrase and content_hits >= 3


def _can_bypass_guarded_summary_floor(reasons: list[str], score: float, min_summary_score: float) -> bool:
    if score < max(60.0, min_summary_score - 60.0):
        return False
    if any(reason.startswith(("secret redaction candidate", "matched domain:")) for reason in reasons):
        return True
    has_symbol = "symbol keyword match" in reasons
    has_config = "config file" in reasons
    has_direct_summary_field = any(
        reason.startswith((
            "matched define:",
            "multi-token defines match",
            "matched call:",
            "matched naming keyword:",
            "matched entrypoint:",
            "matched env read:",
            "matched side effect:",
            "matched external system:",
        ))
        for reason in reasons
    )
    content_hits = 0
    for reason in reasons:
        match = re.match(r"content keyword match \((\d+)\)", reason)
        if match:
            content_hits = max(content_hits, int(match.group(1)))
    return has_direct_summary_field and (has_symbol or has_config or content_hits >= 1)


def _has_release_metadata_reason(reasons: list[str]) -> bool:
    return any(reason.startswith("release/version metadata") for reason in reasons)


def _is_primary_release_metadata(path: str, reasons: list[str]) -> bool:
    if not _has_release_metadata_reason(reasons):
        return False
    name = Path(path).name.lower()
    return name in {"pyproject.toml", "package.json", "cargo.toml", "pom.xml", "__init__.py", "__about__.py", "_version.py", "version.py"}


def _is_secondary_release_metadata(path: str, reasons: list[str]) -> bool:
    return _has_release_metadata_reason(reasons) and not _is_primary_release_metadata(path, reasons)


def _is_lock_or_generated_path(path: str) -> bool:
    name = Path(path).name.lower()
    parts = {part.lower() for part in Path(path).parts}
    if parts & {"dist", "build", "coverage", "vendor", "generated", "__generated__", "snapshots", "__snapshots__"}:
        return True
    return name in {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.lock",
        "poetry.lock",
        "gemfile.lock",
    } or name.endswith((".snap", ".snapshot"))


def _compressed_context_family(path: str, reasons: list[str]) -> tuple[str, int] | None:
    reason_text = " ".join(reasons).lower()
    explicit_test_task = "explicit test task file" in reasons
    if _is_lock_or_generated_path(path):
        if _has_release_metadata_reason(reasons):
            return "lock-release", 1
        return "lock-generated", 0
    if _has_release_metadata_reason(reasons):
        return "release-metadata", 2
    if _is_test_path(path):
        return "tests", 4 if explicit_test_task else 2
    if "config file" in reasons:
        has_specific_path_match = any(reason.startswith("multi-term path match") for reason in reasons)
        return "config", 2 if has_specific_path_match else 1
    if _is_docs_path(path):
        return "docs", 1
    if _is_example_or_playground_path(path):
        return "examples", 1
    if _is_direct_source_candidate(path, reasons):
        return None
    if (
        "recall neighbor" in reason_text
        or "workspace match" in reason_text
        or "large supported file" in reason_text
        or "second-pass recall neighbor" in reason_text
    ):
        return "expansion", 1
    return None


def _package_root(path: str) -> str | None:
    parts = [part for part in Path(path).parts if part]
    if len(parts) >= 2 and parts[0] == "packages":
        return "/".join(parts[:2])
    return None


def _playground_root(path: str) -> str | None:
    parts = [part for part in Path(path).parts if part]
    if len(parts) >= 2 and parts[0] == "playground":
        return "/".join(parts[:2])
    return None


def _can_overflow_same_package_test(path: str, reasons: list[str], selected: list[SelectedFile]) -> bool:
    package = _package_root(path)
    if package is None or not _is_test_path(path):
        return False
    if "explicit test task file" in reasons:
        return False
    has_direct_test_evidence = any(reason.startswith("direct content evidence") for reason in reasons)
    has_paired_source_reason = any(reason.startswith("test for high-scoring ") for reason in reasons)
    has_strong_task_evidence = _content_keyword_hits(reasons) >= 4 or any(
        reason.startswith("keyword phrase match:")
        for reason in reasons
    )
    if not (has_direct_test_evidence and has_paired_source_reason and has_strong_task_evidence):
        return False
    selected_package_sources = {
        sf.path
        for sf in selected
        if _package_root(sf.path) == package and not _is_test_path(sf.path)
    }
    if not selected_package_sources:
        return False
    for reason in reasons:
        if not reason.startswith("test for high-scoring "):
            continue
        source_path = reason.removeprefix("test for high-scoring ").strip()
        if source_path in selected_package_sources:
            return True
    return False


def _can_overflow_same_playground_test(path: str, reasons: list[str], selected: list[SelectedFile]) -> bool:
    playground = _playground_root(path)
    if playground is None or not _is_test_path(path):
        return False
    has_scope_evidence = "conventional scope path match" in reasons
    has_phrase_evidence = any(reason.startswith("keyword phrase match:") for reason in reasons)
    has_content_evidence = _content_keyword_hits(reasons) >= 3 or any(
        reason.startswith(("matched call:", "direct content evidence"))
        for reason in reasons
    )
    if not (has_scope_evidence and (has_phrase_evidence or has_content_evidence)):
        return False
    return any(_playground_root(sf.path) == playground for sf in selected)


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
    max_weak_signal_files: int = 0,
    strict_summary_selection: bool = False,
    omitted_relevant_files: list[OmittedRelevantFile] | None = None,
) -> tuple[list[SelectedFile], list[Receipt]]:
    opts = _MODE_WEIGHTS[mode]
    selected: list[SelectedFile] = []
    receipts: list[Receipt] = []
    tokens_used = 0
    summaries_used = 0
    kw = keywords or set()
    budget_pressure = budget < 12000 or len(changed_paths) > 5
    unrelated_changed_cap = 3 if len(changed_paths) > 5 else 0
    unrelated_changed_used = 0
    weak_signal_used = 0
    paired_test_overflow_used = 0
    playground_test_overflow_used = 0
    primary_release_metadata_selected = False
    compressed_family_counts: dict[str, int] = {}

    ranked = sorted(
        scored,
        key=lambda item: _selection_priority(item, changed_paths, max_file_tokens, summaries=summaries),
        reverse=True,
    )
    ordered = _reserve_bucket_order(ranked, changed_paths, budget)
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
        weak_signal_only = not is_changed and _is_weak_signal_candidate(reasons)
        if not is_changed and not opts["include_docs"] and _selection_bucket(fi, reasons, changed_paths) == "docs":
            receipts.append(Receipt(path=fi.path, action="excluded", reason="docs disabled by mode"))
            continue
        if is_changed and not has_task_signal and unrelated_changed_cap:
            if unrelated_changed_used >= unrelated_changed_cap:
                receipts.append(Receipt(path=fi.path, action="excluded", reason="unrelated changed-file safety cap"))
                continue
            unrelated_changed_used += 1
        if weak_signal_only and max_weak_signal_files >= 0 and weak_signal_used >= max_weak_signal_files:
            receipts.append(Receipt(path=fi.path, action="excluded", reason="weak-signal cap reached"))
            continue
        if primary_release_metadata_selected and not is_changed and _is_secondary_release_metadata(fi.path, reasons):
            receipts.append(Receipt(path=fi.path, action="excluded", reason="secondary release metadata skipped after primary"))
            continue
        will_be_summary = not is_changed and not (
            opts["extra_full"] and fi.estimated_tokens <= max_file_tokens
        )
        has_redaction_reason = any(reason.startswith("secret redaction candidate") for reason in reasons)
        if (
            will_be_summary
            and score < min_summary_score
            and not (
                strict_summary_selection
                and (
                    has_redaction_reason
                    or (not selected and _can_bypass_guarded_summary_floor(reasons, score, min_summary_score))
                )
            )
        ):
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
        elif weak_signal_only and summary_data:
            mode_str = "summary"
            tok = _summary_tokens(summary_data, min(fi.estimated_tokens, 200))
            reasons = reasons + ["weak-signal file compressed to summary"]
        elif weak_signal_only:
            mode_str = "summary"
            tok = min(fi.estimated_tokens, 200)
            reasons = reasons + ["weak-signal file compressed to summary"]
        elif summary_data and skeleton and score >= 160:
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

        compressed_context = mode_str in ("summary", "skeleton")
        if compressed_context and not is_changed and mode == "balanced":
            weak_noise_reason = _weak_compressed_noise_reason(fi.path, reasons, kw)
            if weak_noise_reason:
                receipts.append(Receipt(path=fi.path, action="excluded", reason=weak_noise_reason))
                continue

        if strict_summary_selection and compressed_context and not is_changed and not _has_strict_summary_support(reasons, fi.path):
            receipts.append(Receipt(path=fi.path, action="excluded", reason="compressed context needs stronger support signal"))
            continue

        if strict_summary_selection and compressed_context and not is_changed and mode == "balanced":
            family_cap = _compressed_context_family(fi.path, reasons)
            if family_cap is not None:
                family, cap = family_cap
                if compressed_family_counts.get(family, 0) >= cap:
                    receipts.append(Receipt(path=fi.path, action="excluded", reason=f"{family} compressed context cap reached"))
                    continue

        paired_test_overflow = False
        playground_test_overflow = False
        if compressed_context and max_summary_files > 0 and summaries_used >= max_summary_files:
            paired_test_overflow = (
                paired_test_overflow_used < 1
                and mode == "balanced"
                and not changed_paths
                and _can_overflow_same_package_test(fi.path, reasons, selected)
            )
            playground_test_overflow = (
                playground_test_overflow_used < 1
                and mode == "balanced"
                and not changed_paths
                and _can_overflow_same_playground_test(fi.path, reasons, selected)
            )
            if not paired_test_overflow and not playground_test_overflow:
                receipts.append(Receipt(path=fi.path, action="excluded", reason="compressed context cap reached"))
                continue
            reasons = reasons + [
                "same-package test overflow" if paired_test_overflow else "same-playground test overflow"
            ]

        if tokens_used + tok > budget:
            if omitted_relevant_files is not None:
                omitted_relevant_files.append(
                    OmittedRelevantFile(
                        path=fi.path,
                        score=score,
                        reasons=reasons,
                        estimated_tokens=fi.estimated_tokens,
                        suggested_mode=mode_str,
                        omission_reason="budget exhausted",
                        risk=classify_omission_risk(fi.path, reasons, score),
                    )
                )
            receipts.append(Receipt(path=fi.path, action="excluded", reason="budget exhausted"))
            continue

        tokens_used += tok
        if compressed_context:
            summaries_used += 1
        if paired_test_overflow:
            paired_test_overflow_used += 1
        if playground_test_overflow:
            playground_test_overflow_used += 1
        if weak_signal_only:
            weak_signal_used += 1
        if _is_primary_release_metadata(fi.path, reasons):
            primary_release_metadata_selected = True
        if strict_summary_selection and compressed_context and not is_changed and mode == "balanced":
            family_cap = _compressed_context_family(fi.path, reasons)
            if family_cap is not None:
                family, _cap = family_cap
                compressed_family_counts[family] = compressed_family_counts.get(family, 0) + 1

        # Build symbol list
        syms: list[Symbol] = []
        if summary_data and mode_str in ("symbols", "skeleton"):
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
