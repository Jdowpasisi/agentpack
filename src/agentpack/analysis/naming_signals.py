from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agentpack.analysis.symbols import extract_symbols


_GENERIC_PUBLIC_STEMS = {
    "base",
    "common",
    "data",
    "handle",
    "helper",
    "manager",
    "misc",
    "process",
    "processor",
    "run",
    "service",
    "thing",
    "tool",
    "util",
    "utils",
}

_GENERIC_FILE_STEMS = {"base", "common", "helpers", "misc", "shared", "util", "utils"}
_IGNORE_TOKENS = {"api", "app", "class", "component", "controller", "file", "function", "handler", "http", "method", "module", "page", "route", "service", "test"}
_DOMAIN_HINTS = {
    "auth", "billing", "cache", "chart", "checkout", "compatibility", "config",
    "context", "cursor", "env", "invoice", "jwt", "kundali", "mcp", "notification",
    "otp", "pack", "payment", "ranking", "redis", "repo", "search", "session",
    "stats", "stripe", "summaries", "summary", "token", "watch", "webhook",
}
_ACTION_HINTS = {
    "add", "apply", "build", "check", "collect", "create", "delete", "dispatch",
    "enrich", "explain", "extract", "fetch", "find", "generate", "get", "infer",
    "install", "issue", "load", "manage", "pack", "parse", "rank", "read",
    "refresh", "render", "resolve", "save", "scan", "score", "select", "send",
    "start", "stop", "summarize", "sync", "track", "update", "validate", "verify",
    "watch", "write",
}


@dataclass
class PublicNameSignal:
    name: str
    label: str
    keywords: list[str]
    reasons: list[str]


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    raw = re.split(r"[^a-zA-Z0-9]+", spaced.lower())
    return [tok for tok in raw if tok]


def classify_public_name(name: str) -> PublicNameSignal:
    tokens = name_tokens(name)
    meaningful = [tok for tok in tokens if len(tok) >= 3 and tok not in _IGNORE_TOKENS]
    generic = [tok for tok in meaningful if tok in _GENERIC_PUBLIC_STEMS]
    domain = [tok for tok in meaningful if tok in _DOMAIN_HINTS]
    action = [tok for tok in meaningful if tok in _ACTION_HINTS]

    if len(meaningful) == 1 and meaningful[0] in _GENERIC_PUBLIC_STEMS:
        return PublicNameSignal(name=name, label="generic", keywords=meaningful, reasons=["unqualified generic public stem"])
    if domain and (action or len(meaningful) >= 2):
        return PublicNameSignal(name=name, label="domain_revealing", keywords=_dedupe([*domain, *action, *meaningful]), reasons=["domain-qualified public name"])
    if len(meaningful) >= 2 and not generic:
        return PublicNameSignal(name=name, label="domain_revealing", keywords=meaningful, reasons=["multi-part public name"])
    if generic and len(meaningful) == len(generic):
        return PublicNameSignal(name=name, label="generic", keywords=meaningful, reasons=["mostly generic public stems"])
    return PublicNameSignal(name=name, label="neutral", keywords=meaningful, reasons=[])


def filename_signal(path: str) -> PublicNameSignal:
    stem = Path(path).stem
    signal = classify_public_name(stem)
    if signal.label == "neutral" and stem.lower() in _GENERIC_FILE_STEMS:
        return PublicNameSignal(name=stem, label="generic", keywords=[stem.lower()], reasons=["generic filename stem"])
    return signal


def collect_public_name_candidates(path: Path, language: str | None) -> list[str]:
    if language in {"javascript", "typescript"}:
        return _collect_js_export_names(path)

    candidates: list[str] = []
    for sym in extract_symbols(path, language):
        tail = sym.name.split(".")[-1]
        if tail.startswith("_"):
            continue
        candidates.append(sym.name)
    return _dedupe(candidates)


def summarize_naming_signals(path: str, public_names: list[str], extra_names: list[str] | None = None) -> tuple[list[str], list[str]]:
    signals: list[str] = []
    keywords: list[str] = []
    for signal in [filename_signal(path), *[classify_public_name(name.split(".")[-1]) for name in public_names]]:
        if signal.label == "domain_revealing":
            signals.append(f"strong public name: {signal.name}")
        elif signal.label == "generic":
            signals.append(f"generic public name: {signal.name}")
        keywords.extend(signal.keywords)
    for name in extra_names or []:
        extra_signal = classify_public_name(name)
        if extra_signal.label == "domain_revealing":
            signals.append(f"strong public name: {name}")
        keywords.extend(extra_signal.keywords)
    return _dedupe(signals)[:12], _dedupe(keywords)[:12]


def _collect_js_export_names(path: Path) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []

    names: list[str] = []
    patterns = [
        re.compile(r"export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\("),
        re.compile(r"export\s+(?:default\s+)?class\s+(\w+)"),
        re.compile(r"export\s+(?:const|let|var)\s+(\w+)\s*="),
    ]
    for pattern in patterns:
        names.extend(pattern.findall(text))
    return _dedupe(names)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
