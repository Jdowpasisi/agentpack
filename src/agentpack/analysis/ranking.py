from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.models import DependencyGraph, FileInfo
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

    # streaming / SSE / websocket
    "stream": frozenset({"sse", "websocket", "ws", "chunk", "realtime", "push", "subscribe", "channel"}),
    "sse": frozenset({"stream", "eventstream", "push", "realtime", "subscribe"}),
    "websocket": frozenset({"stream", "ws", "socket", "realtime", "channel", "push"}),
    "realtime": frozenset({"stream", "sse", "websocket", "push", "subscribe", "channel"}),

    # webhooks / events
    "webhook": frozenset({"event", "callback", "notify", "dispatch", "trigger", "listener", "handler"}),
    "event": frozenset({"webhook", "listener", "handler", "dispatch", "emit", "publish", "subscribe", "bus"}),

    # pagination
    "pagination": frozenset({"page", "cursor", "offset", "limit", "paginate", "scroll", "infinite"}),
    "paginate": frozenset({"page", "cursor", "offset", "limit", "pagination"}),

    # validation / schema
    "validation": frozenset({"validate", "schema", "sanitize", "constraint", "rule", "pydantic", "zod", "yup"}),
    "validate": frozenset({"validation", "schema", "sanitize", "constraint"}),
    "schema": frozenset({"validate", "model", "serializer", "deserializer", "marshal", "unmarshal"}),

    # deployment / infra
    "deploy": frozenset({"release", "rollout", "container", "docker", "k8s", "kubernetes", "terraform", "ci", "cd"}),
    "docker": frozenset({"container", "image", "compose", "deploy", "k8s", "registry"}),
    "kubernetes": frozenset({"k8s", "pod", "deployment", "service", "ingress", "helm", "container"}),

    # email / notifications
    "email": frozenset({"smtp", "sendgrid", "mailgun", "ses", "template", "notification", "mailer"}),
    "notification": frozenset({"email", "push", "sms", "alert", "webhook", "event"}),

    # payment / billing
    "payment": frozenset({"stripe", "paypal", "billing", "invoice", "charge", "subscription", "checkout"}),
    "billing": frozenset({"payment", "subscription", "invoice", "charge", "plan", "tier"}),

    # file / upload
    "file": frozenset({"upload", "download", "storage", "s3", "blob", "multipart", "attachment", "disk"}),

    # test / testing
    "test": frozenset({"spec", "fixture", "mock", "stub", "assert", "expect", "describe", "jest", "pytest"}),
    "mock": frozenset({"stub", "spy", "patch", "fixture", "test", "fake"}),

    # config / env
    "config": frozenset({"env", "settings", "environment", "dotenv", "toml", "yaml", "ini", "conf"}),
    "env": frozenset({"config", "settings", "environment", "dotenv", "variable"}),

    # serialization
    "serialize": frozenset({"json", "marshal", "encode", "decode", "pickle", "protobuf", "msgpack"}),
    "deserialize": frozenset({"json", "unmarshal", "decode", "parse", "protobuf"}),

    # health check / liveness
    "health": frozenset({"ping", "liveness", "readiness", "probe", "heartbeat", "status", "check"}),
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


def _add_keyword_weight(weights: dict[str, float], keyword: str, weight: float) -> None:
    weights[keyword] = max(weights.get(keyword, 0.0), weight)


def extract_keyword_weights(task: str) -> dict[str, float]:
    words = re.split(r"[^a-zA-Z0-9]+", task.lower())
    keyword_weights: dict[str, float] = {}
    for word in words:
        if len(word) < 3:
            continue
        if word in _STOPWORDS:
            continue
        _add_keyword_weight(keyword_weights, word, 1.0)
        if word in _VARIANTS:
            _add_keyword_weight(keyword_weights, _VARIANTS[word], 0.75)

    # Expand via concept map one level only. Expanded concepts are weaker than
    # literal task words so broad terms like "task" do not dominate ranking.
    expanded: dict[str, float] = {}
    for kw in keyword_weights:
        if kw in _CONCEPT_MAP:
            for synonym in _CONCEPT_MAP[kw]:
                _add_keyword_weight(expanded, synonym, 0.35)
                if synonym in _VARIANTS:
                    _add_keyword_weight(expanded, _VARIANTS[synonym], 0.35)
    for kw, weight in expanded.items():
        _add_keyword_weight(keyword_weights, kw, weight)
    return keyword_weights


def extract_keywords(task: str) -> set[str]:
    return set(extract_keyword_weights(task))


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
        if fi is None:
            continue
        if fi.content is not None:
            text = fi.content
        elif fi.abs_path.exists():
            try:
                text = fi.abs_path.read_text(errors="replace")
            except OSError:
                continue
        else:
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


def enrich_keyword_weights_from_files(
    keyword_weights: dict[str, float],
    changed_paths: set[str],
    files: list[FileInfo],
    max_new_keywords: int = 20,
) -> dict[str, float]:
    enriched = dict(keyword_weights)
    enriched_keywords = enrich_keywords_from_files(set(keyword_weights), changed_paths, files, max_new_keywords)
    for keyword in enriched_keywords - set(keyword_weights):
        enriched[keyword] = 0.5
    return enriched


def _tokens_for_match(text: str) -> set[str]:
    """Return identifier-ish tokens for exact keyword matching."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw_tokens = re.split(r"[^a-zA-Z0-9]+", spaced.lower())
    return {tok for tok in raw_tokens if tok}


def _keyword_token_weights(keywords: set[str] | dict[str, float]) -> dict[str, float]:
    if isinstance(keywords, dict):
        items = keywords.items()
    else:
        items = ((keyword, 1.0) for keyword in keywords)

    token_weights: dict[str, float] = {}
    for keyword, weight in items:
        for token in _tokens_for_match(keyword):
            if len(token) >= 3:
                token_weights[token] = max(token_weights.get(token, 0.0), weight)
    return token_weights


def _match_weight(text: str, keywords: set[str] | dict[str, float]) -> float:
    token_weights = _keyword_token_weights(keywords)
    matches = _tokens_for_match(text) & set(token_weights)
    return max((token_weights[token] for token in matches), default=0.0)


def _path_matches_keywords(path: str, keywords: set[str] | dict[str, float]) -> float:
    return _match_weight(path, keywords)


def _content_matches_keywords(text: str, keywords: set[str] | dict[str, float]) -> tuple[int, float]:
    token_weights = _keyword_token_weights(keywords)
    text_tokens = _tokens_for_match(text)
    matches = text_tokens & set(token_weights)
    return len(matches), sum(token_weights[token] for token in matches)


def _symbol_matches_keywords(symbols: list[str], keywords: set[str] | dict[str, float]) -> float:
    best_weight = 0.0
    for sym in symbols:
        best_weight = max(best_weight, _match_weight(sym, keywords))
    return best_weight


def score_files(
    files: list[FileInfo],
    changed_paths: set[str],
    staged_paths: set[str],
    recently_modified: list[str],
    dep_graph: "DependencyGraph | dict",
    keywords: set[str] | dict[str, float],
    include_tests: bool = True,
    include_configs: bool = True,
    weights: ScoringWeights | None = None,
    summaries: dict | None = None,
    churn_counts: dict[str, int] | None = None,
) -> list[tuple[FileInfo, float, list[str]]]:
    from agentpack.core.models import DependencyGraph as _DG
    if not isinstance(dep_graph, _DG):
        dep_graph = _DG()
    w = weights or _DEFAULT_WEIGHTS
    all_paths = {f.path for f in files}
    results: list[tuple[FileInfo, float, list[str]]] = []
    recently_set = set(recently_modified[:20])

    churn_threshold: int | None = None
    if churn_counts:
        vals = sorted(churn_counts.values(), reverse=True)
        cutoff_idx = max(0, len(vals) // 10 - 1)  # top 10%
        churn_threshold = vals[cutoff_idx] if vals else None

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

        filename_weight = _path_matches_keywords(fi.path, keywords)
        if filename_weight > 0:
            score += w.filename_keyword * filename_weight
            reasons.append("filename keyword match")

        node = dep_graph.get(fi.path)
        sym_names: list[str] = []
        if summaries and fi.path in summaries:
            raw_syms = summaries[fi.path].get("symbols", [])
            sym_names = [
                (s["name"] if isinstance(s, dict) else s.name)
                for s in raw_syms
            ]
        symbol_weight = _symbol_matches_keywords(sym_names, keywords)
        if symbol_weight > 0:
            score += w.symbol_keyword * symbol_weight
            reasons.append("symbol keyword match")

        if fi.content is not None:
            hits, hit_weight = _content_matches_keywords(fi.content, keywords)
            if hits > 0:
                score += min(w.content_keyword_max, hit_weight * w.content_keyword_per_hit)
                reasons.append(f"content keyword match ({hits})")
        elif fi.abs_path.exists():
            try:
                text = fi.abs_path.read_text(errors="replace")
                hits, hit_weight = _content_matches_keywords(text, keywords)
                if hits > 0:
                    score += min(w.content_keyword_max, hit_weight * w.content_keyword_per_hit)
                    reasons.append(f"content keyword match ({hits})")
            except OSError:
                pass

        for dep_path in node.imports:
            if dep_path in changed_paths or _path_matches_keywords(dep_path, keywords) > 0:
                score += w.direct_dep
                reasons.append("direct dependency of changed file")
                break

        for other_path, other_node in dep_graph.items():
            if fi.path in other_node.imports and other_path in changed_paths:
                score += w.reverse_dep
                reasons.append("reverse dependency")
                break

        if include_tests:
            tests = node.tests
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

        if _is_knowledge_file(fi.path):
            score += w.knowledge_file
            reasons.append("knowledge/architecture doc")

        if fi.path in recently_set:
            score += w.recently_modified
            reasons.append("recently modified")

        if churn_counts and churn_threshold is not None:
            count = churn_counts.get(fi.path, 0)
            if count >= churn_threshold:
                score += w.churn_high
                reasons.append(f"high churn ({count} commits)")

        if fi.too_large and score < 50:
            score += w.large_unrelated_penalty
            reasons.append("large unrelated file")

        results.append((fi, score, reasons))

    return results


def boost_paired_tests(
    scored: list[tuple[FileInfo, float, list[str]]],
    weights: ScoringWeights | None = None,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Boost test files that pair with high-scoring source files.

    Only applies to test files not already boosted by changed_paths.
    Threshold: source must score above the median non-test score.
    """
    w = weights or _DEFAULT_WEIGHTS
    non_test_scores = [
        score for fi, score, _ in scored
        if not fi.ignored and not fi.binary and not _is_test_file(fi.path) and score > 0
    ]
    if not non_test_scores:
        return scored
    threshold = sorted(non_test_scores)[len(non_test_scores) // 2]  # median

    source_scores = {
        fi.path: score for fi, score, _ in scored
        if not _is_test_file(fi.path) and score >= threshold
    }

    result = []
    for fi, score, reasons in scored:
        if _is_test_file(fi.path):
            already_boosted = any("test for" in r for r in reasons)
            if not already_boosted:
                for src_path, src_score in source_scores.items():
                    if _test_matches_source(fi.path, src_path):
                        score += w.related_test
                        reasons = reasons + [f"test for high-scoring {src_path}"]
                        break
        result.append((fi, score, reasons))
    return result


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


_KNOWLEDGE_NAMES = {
    "decisions", "adr", "architecture", "contributing", "design",
    "technical", "tradeoffs", "rfc", "proposal",
}
_KNOWLEDGE_DIRS = {"adr", "adrs", "decisions", "rfcs", "proposals", "design"}


def _is_knowledge_file(path: str) -> bool:
    p = Path(path)
    stem_lower = p.stem.lower()
    # Match ADR-NNN.md patterns and known doc names
    if stem_lower in _KNOWLEDGE_NAMES:
        return p.suffix.lower() == ".md"
    if re.match(r"adr[-_]?\d+", stem_lower):
        return True
    # Any .md file in a known docs dir
    if any(part.lower() in _KNOWLEDGE_DIRS for part in p.parts):
        return p.suffix.lower() == ".md"
    return False
