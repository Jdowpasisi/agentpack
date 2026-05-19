from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.models import DependencyGraph, FileInfo
from agentpack.core.config import ScoringWeights
from agentpack.analysis.monorepo import workspace_for_path, workspace_tokens

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "that", "this", "these", "those", "it", "its",
    "from", "not", "we", "our", "you", "your", "they", "them", "their",
    "file", "files", "code", "function", "method", "class", "module",
    "use", "using", "used", "how", "what", "when", "where", "why",
}

_GENERIC_TASK_TERMS = {
    "add", "added", "change", "changed", "changes", "clean", "cleanup",
    "code", "commit", "context", "debug", "dev", "development", "doc",
    "docs", "eval", "evals", "feature", "fix", "freshness", "general",
    "impl", "implement", "implementation", "improve", "issue", "metric", "metrics",
    "noise", "noisy", "package", "pack", "packs", "release", "repo",
    "source", "sync", "task", "tasks", "test", "tests", "update", "use",
    "useful", "usefulness", "version", "workflow", "workflows",
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

    # astrology / charting product domains
    "kundali": frozenset({"astrology", "horoscope", "chart", "birth", "natal", "compatibility", "matching"}),
    "astrology": frozenset({"kundali", "horoscope", "chart", "birth", "natal", "compatibility"}),
    "horoscope": frozenset({"astrology", "kundali", "chart", "natal"}),
    "compatibility": frozenset({"matching", "match", "compare", "score", "relationship"}),
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
    "verification": "verify",
    "verified": "verify",
    "verifying": "verify",
    "payments": "payment",
    "webhooks": "webhook",
    "variables": "variable",
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

_IMPLEMENTATION_ROLE_TOKENS = {
    "api", "apis", "route", "routes", "router", "endpoint", "endpoints",
    "controller", "controllers", "service", "services", "handler", "handlers",
    "resolver", "resolvers", "schema", "schemas", "model", "models",
    "repository", "repositories", "repo", "repos", "client", "clients",
    "adapter", "adapters", "provider", "providers", "serializer",
    "serializers", "validator", "validators", "worker", "workers", "job",
    "jobs", "mailer", "mailers", "migration", "migrations", "paginator",
    "pagination",
}

_ENTRYPOINT_ROLE_TOKENS = {
    "page", "pages", "screen", "screens", "view", "views", "component",
    "components", "api", "route", "routes", "router", "controller",
    "controllers", "endpoint", "endpoints", "handler", "handlers",
    "webhook", "webhooks",
}

_PATH_NOISE_TOKENS = {
    "src", "app", "apps", "lib", "libs", "pkg", "packages", "backend",
    "frontend", "server", "client", "web", "mobile", "index", "main",
    "test", "tests", "spec", "specs",
} | _IMPLEMENTATION_ROLE_TOKENS | _ENTRYPOINT_ROLE_TOKENS

_FILENAME_CORROBORATION_PREFIXES = (
    "modified",
    "staged",
    "symbol keyword match",
    "content keyword match",
    "matched ",
    "direct dependency",
    "reverse dependency",
    "has related tests",
    "test for",
    "config file",
    "knowledge/architecture doc",
    "implementation role match",
    "recently modified",
    "historically co-changed",
    "recall neighbor",
    "workspace match",
)


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
        literal_weight = 0.25 if word in _GENERIC_TASK_TERMS else 1.0
        _add_keyword_weight(keyword_weights, word, literal_weight)
        if word in _VARIANTS:
            variant = _VARIANTS[word]
            variant_weight = 0.25 if variant in _GENERIC_TASK_TERMS else min(0.75, literal_weight)
            _add_keyword_weight(keyword_weights, variant, variant_weight)

    # Expand via concept map one level only. Expanded concepts are weaker than
    # literal task words so broad terms like "task" do not dominate ranking.
    expanded: dict[str, float] = {}
    for kw in keyword_weights:
        if kw in _CONCEPT_MAP and kw not in _GENERIC_TASK_TERMS:
            for synonym in _CONCEPT_MAP[kw]:
                _add_keyword_weight(expanded, synonym, 0.35)
                if synonym in _VARIANTS:
                    _add_keyword_weight(expanded, _VARIANTS[synonym], 0.35)
    for kw, weight in expanded.items():
        _add_keyword_weight(keyword_weights, kw, weight)
    return keyword_weights


def generic_task_term_ratio(task: str) -> float:
    words = [
        word for word in re.split(r"[^a-zA-Z0-9]+", task.lower())
        if len(word) >= 3 and word not in _STOPWORDS
    ]
    if not words:
        return 0.0
    generic = sum(1 for word in words if word in _GENERIC_TASK_TERMS)
    return generic / len(words)


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


def _path_tokens(path: str) -> set[str]:
    p = Path(path)
    pieces = list(p.parts[:-1]) + [p.stem]
    tokens: set[str] = set()
    for piece in pieces:
        tokens |= _tokens_for_match(piece)
    return tokens


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


def _summary_values(summary: object, field: str) -> list[str]:
    if summary is None:
        return []
    if isinstance(summary, dict):
        value = summary.get(field)
    else:
        value = getattr(summary, field, None)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and "name" in item:
                result.append(str(item["name"]))
            elif hasattr(item, "name"):
                result.append(str(item.name))
            else:
                result.append(str(item))
        return result
    return [str(value)]


def _best_summary_match(
    values: list[str],
    keywords: set[str] | dict[str, float],
    *,
    presence_terms: set[str] | None = None,
) -> tuple[str, float] | None:
    if not values:
        return None
    best_value = ""
    best_weight = 0.0
    for value in values:
        weight = _match_weight(value, keywords)
        if weight > best_weight:
            best_value = value
            best_weight = weight
    if best_weight > 0:
        return best_value, best_weight
    if presence_terms and (set(_keyword_token_weights(keywords)) & presence_terms):
        return values[0], 0.6
    return None


def _short_reason_value(value: str, max_len: int = 80) -> str:
    clean = " ".join(value.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "..."


_GENERIC_SUMMARY_VALUES = {
    "HTTP API route handler",
    "React UI component",
    "React page component",
    "React page: page",
    "entrypoint",
    "configuration",
    "api",
    "frontend",
    "data",
}


def _summary_boost_weight(field: str, value: str, amount: float) -> float:
    if field in {"role", "domain"} and value in _GENERIC_SUMMARY_VALUES:
        return min(amount, 16.0)
    if field == "ranking_keywords" and value in {"handler", "http", "route", "api", "component", "page"}:
        return min(amount, 10.0)
    return amount


def _has_role(path: str, roles: set[str]) -> bool:
    return bool(_path_tokens(path) & roles)


def _domain_tokens(path: str) -> set[str]:
    return {tok for tok in _path_tokens(path) if len(tok) >= 3 and tok not in _PATH_NOISE_TOKENS}


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
    co_changed_paths: dict[str, int] | None = None,
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
        summary_data = summaries.get(fi.path) if summaries and fi.path in summaries else None
        if summary_data:
            sym_names = _summary_values(summary_data, "symbols")
        symbol_weight = _symbol_matches_keywords(sym_names, keywords)
        if symbol_weight > 0:
            score += w.symbol_keyword * symbol_weight
            reasons.append("symbol keyword match")

        if summary_data:
            summary_boosts = [
                ("entrypoints", "matched entrypoint", 72.0, None),
                ("external_systems", "matched external system", 64.0, None),
                ("role", "matched role keyword", 56.0, None),
                ("domain", "matched domain", 50.0, None),
                ("ranking_keywords", "matched ranking keyword", 44.0, None),
                ("defines", "matched define", 42.0, None),
                ("reads_env", "matched env read", 52.0, {"env", "environment", "variable", "config", "settings"}),
                ("side_effects", "matched side effect", 46.0, {"side", "effect", "effects", "io", "debug"}),
                ("calls", "matched call", 26.0, None),
            ]
            for field, label, amount, presence_terms in summary_boosts:
                match = _best_summary_match(
                    _summary_values(summary_data, field),
                    keywords,
                    presence_terms=presence_terms,
                )
                if not match:
                    continue
                value, match_weight = match
                score += _summary_boost_weight(field, value, amount) * match_weight
                reasons.append(f"{label}: {_short_reason_value(value)}")

            naming_keywords = _summary_values(summary_data, "naming_keywords")
            naming_signals = _summary_values(summary_data, "naming_signals")
            naming_match = _best_summary_match(naming_keywords, keywords)
            if naming_match:
                value, match_weight = naming_match
                score += min(20.0, match_weight * 18.0)
                reasons.append(f"matched naming keyword: {_short_reason_value(value)}")

            generic_public_names = [
                value.split(": ", 1)[1]
                for value in naming_signals
                if value.startswith("generic public name: ")
            ]
            if generic_public_names and filename_weight == 0 and symbol_weight == 0:
                score += min(-6.0, w.weak_filename_match_penalty / 2)
                reasons.append(f"generic public API penalty: {generic_public_names[0]}")

        content_hits = 0
        if fi.content is not None:
            hits, hit_weight = _content_matches_keywords(fi.content, keywords)
            content_hits = hits
            if hits > 0:
                score += min(w.content_keyword_max, hit_weight * w.content_keyword_per_hit)
                reasons.append(f"content keyword match ({hits})")
        elif fi.abs_path.exists():
            try:
                text = fi.abs_path.read_text(errors="replace")
                hits, hit_weight = _content_matches_keywords(text, keywords)
                content_hits = hits
                if hits > 0:
                    score += min(w.content_keyword_max, hit_weight * w.content_keyword_per_hit)
                    reasons.append(f"content keyword match ({hits})")
            except OSError:
                pass

        matched_task_signal = filename_weight > 0 or symbol_weight > 0 or content_hits > 0
        if matched_task_signal and _has_role(fi.path, _IMPLEMENTATION_ROLE_TOKENS):
            score += w.implementation_role
            reasons.append("implementation role match")

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

        if _has_secret_content(fi):
            score += w.modified
            reasons.append("secret redaction candidate")

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

        if co_changed_paths and fi.path in co_changed_paths:
            count = co_changed_paths[fi.path]
            score += w.co_changed * min(1.0, 0.5 + (count / 4))
            reasons.append(f"historically co-changed ({count} commits)")

        if filename_weight > 0 and not _has_filename_corroboration(reasons):
            score = max(1.0, score + w.weak_filename_match_penalty)
            reasons.append(f"weak filename-only match {w.weak_filename_match_penalty:.0f}")

        if fi.too_large and score < 50:
            score += w.large_unrelated_penalty
            reasons.append("large unrelated file")

        results.append((fi, score, reasons))

    return results


def _has_filename_corroboration(reasons: list[str]) -> bool:
    return any(reason.startswith(_FILENAME_CORROBORATION_PREFIXES) for reason in reasons)


def boost_cross_layer_related(
    scored: list[tuple[FileInfo, float, list[str]]],
    keywords: set[str] | dict[str, float],
    weights: ScoringWeights | None = None,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Boost service/controller/schema/handler files near high-scoring entrypoints.

    Full-stack tasks often start from a UI page or route, but the actual fix is
    in a backend service or handler. This boost connects files with shared
    domain tokens while requiring either a task keyword or a high-scoring
    entrypoint seed, so generic services do not all float upward.
    """
    w = weights or _DEFAULT_WEIGHTS
    positive_scores = [score for fi, score, _ in scored if score > 0 and not fi.ignored and not fi.binary]
    if not positive_scores:
        return scored
    threshold = sorted(positive_scores, reverse=True)[max(0, min(4, len(positive_scores) - 1))]

    keyword_tokens = set(_keyword_token_weights(keywords))
    seed_domains: set[str] = set()
    for fi, score, _reasons in scored:
        if score >= threshold and _has_role(fi.path, _ENTRYPOINT_ROLE_TOKENS):
            seed_domains |= _domain_tokens(fi.path)

    related_terms = (keyword_tokens | seed_domains) - _PATH_NOISE_TOKENS
    if not related_terms:
        return scored

    result: list[tuple[FileInfo, float, list[str]]] = []
    for fi, score, reasons in scored:
        if not fi.ignored and not fi.binary and _has_role(fi.path, _IMPLEMENTATION_ROLE_TOKENS):
            if _domain_tokens(fi.path) & related_terms and "cross-layer related implementation" not in reasons:
                score += w.cross_layer_related
                reasons = reasons + ["cross-layer related implementation"]
        result.append((fi, score, reasons))
    return result


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


def boost_recall_neighbors(
    scored: list[tuple[FileInfo, float, list[str]]],
    dep_graph: DependencyGraph,
    changed_paths: set[str],
    weights: ScoringWeights | None = None,
    *,
    seed_limit: int = 8,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Boost import/reverse-import/test neighbors of strong seed files.

    This raises recall for files that do not match task words directly but sit
    next to a changed or high-scoring file in the dependency graph.
    """
    if not scored:
        return scored
    w = weights or _DEFAULT_WEIGHTS
    path_set = {fi.path for fi, _score, _reasons in scored}
    seed_candidates = [
        (fi.path, score)
        for fi, score, _reasons in scored
        if fi.path in changed_paths or score >= 120
    ]
    seed_paths = [
        path for path, _score in sorted(
            seed_candidates,
            key=lambda item: (item[0] not in changed_paths, -item[1], item[0]),
        )[:seed_limit]
    ]
    if not seed_paths:
        return scored

    boosts: dict[str, tuple[float, str]] = {}
    for seed in seed_paths:
        node = dep_graph.get(seed)
        neighbors = [*node.imports, *node.imported_by, *node.tests]
        for neighbor in neighbors:
            if neighbor == seed or neighbor not in path_set:
                continue
            amount = w.recall_neighbor + (8 if seed in changed_paths else 0)
            current = boosts.get(neighbor)
            if current is None or amount > current[0]:
                boosts[neighbor] = (amount, seed)

    result: list[tuple[FileInfo, float, list[str]]] = []
    for fi, score, reasons in scored:
        boost = boosts.get(fi.path)
        if boost and not fi.ignored and not fi.binary:
            amount, seed = boost
            score += amount
            reasons = reasons + [f"recall neighbor of {seed}"]
        result.append((fi, score, reasons))
    return result


def boost_second_pass_expansion(
    scored: list[tuple[FileInfo, float, list[str]]],
    dep_graph: DependencyGraph,
    keywords: set[str] | dict[str, float],
    weights: ScoringWeights | None = None,
    *,
    seed_limit: int = 10,
    max_boosts: int = 32,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Boost guarded two-hop neighbours around strong first-pass seeds.

    This is deliberately conservative: it only boosts files that are close to a
    strong seed and share task/domain signal, are paired tests, or are config
    files. That raises recall for adjacent implementation files without turning
    broad task wording into repo-wide expansion.
    """
    if not scored:
        return scored
    w = weights or _DEFAULT_WEIGHTS
    path_map = {fi.path: (fi, score, reasons) for fi, score, reasons in scored}
    keyword_tokens = set(_keyword_token_weights(keywords)) - _PATH_NOISE_TOKENS

    seed_paths = [
        fi.path
        for fi, score, reasons in sorted(scored, key=lambda row: row[1], reverse=True)
        if score >= 100
        or any(
            reason.startswith((
                "modified",
                "staged",
                "workspace match",
                "cross-layer related",
                "recall neighbor",
                "historically co-changed",
            ))
            for reason in reasons
        )
    ][:seed_limit]
    if not seed_paths:
        return scored

    boosts: dict[str, tuple[float, str, str]] = {}

    def neighbours(path: str) -> set[str]:
        node = dep_graph.get(path)
        return {p for p in (*node.imports, *node.imported_by, *node.tests) if p in path_map and p != path}

    for seed in seed_paths:
        seed_domains = _domain_tokens(seed) | keyword_tokens
        first_hop = neighbours(seed)
        second_hop = {candidate for hop in first_hop for candidate in neighbours(hop)}
        for candidate in sorted(second_hop - {seed} - first_hop):
            fi, _score, _reasons = path_map[candidate]
            if fi.ignored or fi.binary:
                continue
            candidate_domains = _domain_tokens(candidate)
            is_test_pair = _is_test_file(candidate) and (
                any(_test_matches_source(candidate, hop) for hop in first_hop | {seed})
                or any(_test_matches_source(candidate, hop) for hop in seed_domains)
            )
            has_domain_signal = bool(candidate_domains & seed_domains)
            has_config_signal = _is_config_file(candidate) and bool(seed_domains)
            if not (is_test_pair or has_domain_signal or has_config_signal):
                continue
            amount = w.recall_neighbor * 0.5
            label = "second-pass related test" if is_test_pair else "second-pass recall neighbor"
            if has_domain_signal:
                amount += 4
            current = boosts.get(candidate)
            if current is None or amount > current[0]:
                boosts[candidate] = (amount, seed, label)

    if not boosts:
        return scored
    keep = {
        path: value
        for path, value in sorted(boosts.items(), key=lambda item: item[1][0], reverse=True)[:max_boosts]
    }

    result: list[tuple[FileInfo, float, list[str]]] = []
    for fi, score, reasons in scored:
        boost = keep.get(fi.path)
        if boost:
            amount, seed, label = boost
            score += amount
            reasons = reasons + [f"{label} of {seed}"]
        result.append((fi, score, reasons))
    return result


def boost_monorepo_workspaces(
    scored: list[tuple[FileInfo, float, list[str]]],
    *,
    workspace_roots: list[str],
    workspace_dependency_edges: dict[str, set[str]] | None = None,
    changed_paths: set[str],
    task: str,
    weights: ScoringWeights | None = None,
) -> list[tuple[FileInfo, float, list[str]]]:
    """Boost files in the changed/task-named workspace and workspace deps."""
    if not workspace_roots:
        return scored
    w = weights or _DEFAULT_WEIGHTS
    workspace_dependency_edges = workspace_dependency_edges or {}
    active_workspaces = {
        workspace
        for path in changed_paths
        if (workspace := workspace_for_path(path, workspace_roots))
    }
    task_tokens = _tokens_for_match(task)
    for workspace in workspace_roots:
        if workspace_tokens(workspace) & task_tokens:
            active_workspaces.add(workspace)
    if not active_workspaces:
        return scored
    dependency_workspaces = {
        dep
        for workspace in active_workspaces
        for dep in workspace_dependency_edges.get(workspace, set())
    }
    dependent_workspaces = {
        workspace
        for workspace, deps in workspace_dependency_edges.items()
        if active_workspaces & deps
    }

    result: list[tuple[FileInfo, float, list[str]]] = []
    for fi, score, reasons in scored:
        workspace = workspace_for_path(fi.path, workspace_roots)
        if workspace in active_workspaces and not fi.ignored and not fi.binary:
            score += w.workspace_match
            reasons = reasons + [f"workspace match {workspace}"]
        elif workspace in dependency_workspaces and not fi.ignored and not fi.binary:
            score += w.recall_neighbor
            reasons = reasons + [f"workspace dependency {workspace}"]
        elif workspace in dependent_workspaces and not fi.ignored and not fi.binary:
            score += w.recall_neighbor * 0.5
            reasons = reasons + [f"workspace dependent {workspace}"]
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


def _has_secret_content(fi: FileInfo) -> bool:
    from agentpack.core.redactor import redact_secrets

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
