from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.models import FileInfo
from agentpack.core.config import ScoringWeights

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "that", "this", "these", "those", "it", "its",
    "from", "not", "we", "our", "you", "your", "they", "them", "their",
    "file", "files", "code", "function", "method", "class", "module",
    "use", "using", "used", "how", "what", "when", "where", "why",
}

_CONCEPT_MAP: dict[str, frozenset[str]] = {
    # rate limiting
    "rate": frozenset({"throttle", "ratelimit", "leaky", "bucket", "debounce", "backoff", "quota"}),
    "limiting": frozenset({"throttle", "ratelimit", "leaky", "bucket", "debounce", "quota"}),
    "throttle": frozenset({"rate", "limit", "ratelimit", "leaky", "bucket", "quota"}),

    # authentication
    "auth": frozenset({"jwt", "bearer", "token", "oauth", "credential", "login", "signin", "identity", "principal"}),
    "authentication": frozenset({"jwt", "bearer", "token", "oauth", "credential", "login"}),
    "login": frozenset({"auth", "signin", "credential", "token", "session"}),

    # caching
    "cache": frozenset({"lru", "memoize", "memo", "ttl", "evict", "invalidate", "redis", "memcache"}),
    "caching": frozenset({"lru", "memoize", "memo", "ttl", "evict", "redis"}),

    # queue / messaging
    "queue": frozenset({"broker", "pubsub", "kafka", "rabbitmq", "worker", "job", "task", "celery", "enqueue", "dequeue"}),
    "message": frozenset({"queue", "broker", "pubsub", "event", "dispatch", "emit", "publish", "subscribe"}),

    # database
    "database": frozenset({"db", "orm", "migration", "schema", "query", "repository", "dao", "entity"}),
    "db": frozenset({"database", "orm", "migration", "schema", "query", "repository"}),
    "migration": frozenset({"schema", "database", "db", "alembic", "flyway", "liquibase"}),

    # concurrency
    "concurrency": frozenset({"mutex", "lock", "semaphore", "atomic", "thread", "async", "goroutine", "coroutine"}),
    "concurrent": frozenset({"mutex", "lock", "semaphore", "atomic", "thread", "race", "goroutine"}),
    "race": frozenset({"mutex", "lock", "semaphore", "atomic", "concurrent", "thread"}),
    "async": frozenset({"await", "coroutine", "future", "promise", "concurrent", "thread"}),

    # error handling
    "error": frozenset({"exception", "fault", "failure", "retry", "fallback", "circuit", "breaker"}),
    "retry": frozenset({"backoff", "error", "fault", "resilience", "circuit", "breaker"}),

    # http / api
    "api": frozenset({"endpoint", "route", "handler", "controller", "rest", "graphql", "grpc", "rpc"}),
    "endpoint": frozenset({"route", "handler", "controller", "api", "path", "url"}),
    "middleware": frozenset({"interceptor", "filter", "hook", "plugin", "decorator", "wrapper"}),

    # storage / files
    "storage": frozenset({"disk", "filesystem", "bucket", "blob", "upload", "download", "s3", "gcs"}),
    "upload": frozenset({"storage", "blob", "bucket", "multipart", "stream", "file"}),

    # security
    "security": frozenset({"auth", "permission", "role", "acl", "policy", "rbac", "encrypt", "hash", "sign"}),
    "permission": frozenset({"role", "acl", "policy", "rbac", "auth", "access", "grant", "deny"}),
    "encrypt": frozenset({"decrypt", "cipher", "hash", "sign", "verify", "secret", "key"}),

    # logging / observability
    "log": frozenset({"trace", "metric", "monitor", "observe", "telemetry", "audit", "event"}),
    "metric": frozenset({"log", "trace", "monitor", "observe", "telemetry", "prometheus", "gauge", "counter"}),

    # search
    "search": frozenset({"index", "query", "fulltext", "elasticsearch", "solr", "lucene", "rank", "score"}),
}

_VARIANTS: dict[str, str] = {
    "cancellation": "cancel",
    "cancelled": "cancel",
    "canceling": "cancel",
    "authentication": "auth",
    "authenticated": "auth",
    "authorize": "auth",
    "authorization": "auth",
    "configuration": "config",
    "configured": "config",
    "database": "db",
    "databases": "db",
    "connection": "conn",
    "connections": "conn",
    "management": "manage",
    "manager": "manage",
    "implementation": "impl",
    "implements": "impl",
    "middleware": "middleware",
    "request": "req",
    "response": "res",
    "session": "session",
    "sessions": "session",
    "error": "error",
    "errors": "error",
    "exception": "exception",
    "exceptions": "exception",
    "handler": "handler",
    "handlers": "handler",
    "service": "service",
    "services": "service",
    "endpoint": "endpoint",
    "endpoints": "endpoint",
    "router": "router",
    "routing": "router",
    "redis": "redis",
    "stream": "stream",
    "streaming": "stream",
    "goroutine": "goroutine",
    "channel": "chan",
    "interface": "interface",
    "struct": "struct",
    "trait": "trait",
    "impl": "impl",
}

CONFIG_EXTENSIONS = {
    ".toml", ".yaml", ".yml", ".json", ".env", ".ini", ".cfg", ".conf",
    ".dockerfile", ".makefile",
}
CONFIG_NAMES = {
    "config", "settings", "configuration", "env", ".env",
    "pyproject", "package", "dockerfile", "makefile", "cargo", "go",
    "build", "cmake",
}

_DEFAULT_WEIGHTS = ScoringWeights()


def extract_keywords(task: str) -> set[str]:
    words = re.split(r"[^a-zA-Z0-9]+", task.lower())
    keywords: set[str] = set()
    for word in words:
        if len(word) < 3:
            continue
        if word in _STOPWORDS:
            continue
        keywords.add(word)
        if word in _VARIANTS:
            keywords.add(_VARIANTS[word])

    # expand via concept map (one level only — no recursion to avoid explosion)
    expanded: set[str] = set()
    for kw in keywords:
        if kw in _CONCEPT_MAP:
            for synonym in _CONCEPT_MAP[kw]:
                expanded.add(synonym)
                # also apply _VARIANTS to expanded terms
                if synonym in _VARIANTS:
                    expanded.add(_VARIANTS[synonym])
    keywords.update(expanded)
    return keywords


def enrich_keywords_from_files(
    keywords: set[str],
    changed_paths: set[str],
    files: list[FileInfo],
    max_new_keywords: int = 20,
) -> set[str]:
    """Expand keywords with high-frequency terms from changed file content.

    Reads only the changed files, extracts identifier-like tokens, and adds
    those that appear repeatedly — giving the ranker semantic signal beyond
    the task string alone.
    """
    path_map = {fi.path: fi for fi in files if not fi.ignored and not fi.binary}
    token_freq: dict[str, int] = {}

    for path in changed_paths:
        fi = path_map.get(path)
        if fi is None or not fi.abs_path.exists():
            continue
        try:
            text = fi.abs_path.read_text(errors="replace")
        except OSError:
            continue
        # Extract camelCase/snake_case identifiers and plain words
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text)
        for raw in tokens:
            # Split camelCase into parts
            parts = re.sub(r"([A-Z])", r" \1", raw).lower().split()
            for part in parts:
                if len(part) < 3 or part in _STOPWORDS:
                    continue
                token_freq[part] = token_freq.get(part, 0) + 1

    # Keep tokens that appear ≥3 times and aren't already in keywords
    new_keywords = {
        tok for tok, freq in token_freq.items()
        if freq >= 3 and tok not in keywords
    }

    # Limit to top max_new_keywords by frequency
    top = sorted(new_keywords, key=lambda t: -token_freq[t])[:max_new_keywords]
    return keywords | set(top)


def _path_matches_keywords(path: str, keywords: set[str]) -> bool:
    path_lower = path.lower()
    return any(kw in path_lower for kw in keywords)


def _content_matches_keywords(text: str, keywords: set[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def _symbol_matches_keywords(symbols: list[str], keywords: set[str]) -> bool:
    for sym in symbols:
        if any(kw in sym.lower() for kw in keywords):
            return True
    return False


def score_files(
    files: list[FileInfo],
    changed_paths: set[str],
    staged_paths: set[str],
    recently_modified: list[str],
    dep_graph: dict[str, dict[str, list[str]]],
    keywords: set[str],
    include_tests: bool = True,
    include_configs: bool = True,
    weights: ScoringWeights | None = None,
) -> list[tuple[FileInfo, float, list[str]]]:
    w = weights or _DEFAULT_WEIGHTS
    all_paths = {f.path for f in files}
    results: list[tuple[FileInfo, float, list[str]]] = []
    recently_set = set(recently_modified[:20])

    for fi in files:
        if fi.ignored or fi.binary:
            results.append((fi, w.ignored_penalty, ["ignored/binary"]))
            continue

        score = 0.0
        reasons: list[str] = []

        if fi.path in changed_paths:
            score += w.modified
            reasons.append("modified")

        if fi.path in staged_paths:
            score += w.staged
            reasons.append("staged")

        if _path_matches_keywords(fi.path, keywords):
            score += w.filename_keyword
            reasons.append("filename keyword match")

        graph_entry = dep_graph.get(fi.path, {})
        sym_names = [s["name"] if isinstance(s, dict) else s.name for s in graph_entry.get("symbols", [])]
        if _symbol_matches_keywords(sym_names, keywords):
            score += w.symbol_keyword
            reasons.append("symbol keyword match")

        if fi.abs_path.exists():
            try:
                text = fi.abs_path.read_text(errors="replace")
                hits = _content_matches_keywords(text, keywords)
                if hits > 0:
                    score += min(w.content_keyword_max, hits * w.content_keyword_per_hit)
                    reasons.append(f"content keyword match ({hits})")
            except OSError:
                pass

        for dep_path in graph_entry.get("imports", []):
            if dep_path in changed_paths or _path_matches_keywords(dep_path, keywords):
                score += w.direct_dep
                reasons.append("direct dependency of changed file")
                break

        for other_path, other_entry in dep_graph.items():
            if fi.path in other_entry.get("imports", []) and other_path in changed_paths:
                score += w.reverse_dep
                reasons.append("reverse dependency")
                break

        if include_tests:
            tests = graph_entry.get("tests", [])
            if tests and any(t in all_paths for t in tests):
                score += w.related_test
                reasons.append("has related tests")

            if _is_test_file(fi.path):
                for src_path in changed_paths:
                    if _test_matches_source(fi.path, src_path):
                        score += w.related_test
                        reasons.append(f"test for {src_path}")
                        break

        if include_configs and _is_config_file(fi.path):
            score += w.config_file
            reasons.append("config file")

        if fi.path in recently_set:
            score += w.recently_modified
            reasons.append("recently modified")

        if fi.too_large and score < 50:
            score += w.large_unrelated_penalty
            reasons.append("large unrelated file")

        results.append((fi, score, reasons))

    return results


def _is_test_file(path: str) -> bool:
    p = Path(path)
    return (
        p.stem.startswith("test_")
        or p.stem.endswith("_test")
        or p.stem.endswith(".test")
        or p.stem.endswith(".spec")
        or "tests" in p.parts
        or "__tests__" in p.parts
    )


def _test_matches_source(test_path: str, src_path: str) -> bool:
    src_stem = Path(src_path).stem
    test_stem = Path(test_path).stem
    return src_stem in test_stem or test_stem.replace("test_", "") == src_stem


def _is_config_file(path: str) -> bool:
    p = Path(path)
    return (
        p.suffix.lower() in CONFIG_EXTENSIONS
        or p.stem.lower() in CONFIG_NAMES
    )
