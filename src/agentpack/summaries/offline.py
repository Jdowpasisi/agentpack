from __future__ import annotations

import re
from pathlib import Path

from agentpack.core.models import FileSummary
from agentpack.analysis.symbols import extract_python_symbols, extract_js_symbols
from agentpack.analysis.python_imports import extract_imports as py_imports
from agentpack.analysis.js_ts_imports import extract_imports as js_imports


def summarize(path: str, abs_path: Path, language: str | None, file_hash: str) -> FileSummary:
    if language == "python":
        return _python_summary(path, abs_path, file_hash)
    if language in ("javascript", "typescript"):
        return _js_summary(path, abs_path, language, file_hash)
    return _generic_summary(path, abs_path, language, file_hash)


def _python_summary(path: str, abs_path: Path, file_hash: str) -> FileSummary:
    imports = py_imports(abs_path)
    symbols = extract_python_symbols(abs_path)

    top_level_imports = [i for i in imports if not i.startswith(".")][:8]
    exposed = [s.name for s in symbols if s.kind in ("class", "function")][:8]

    parts = ["Language: Python"]
    if exposed:
        parts.append(f"Exposes: {', '.join(exposed)}")
    if top_level_imports:
        parts.append(f"Imports: {', '.join(top_level_imports)}")
    parts.append(f"Likely responsibility: {_infer_responsibility(path, exposed)}")

    return FileSummary(
        path=path,
        hash=file_hash,
        language="python",
        provider="offline",
        schema_version=1,
        summary="\n- ".join([""] + parts).lstrip("\n- ") if parts else "",
        imports=imports[:20],
        symbols=symbols,
    )


def _js_summary(path: str, abs_path: Path, language: str, file_hash: str) -> FileSummary:
    imports = js_imports(abs_path)
    symbols = extract_js_symbols(abs_path)

    rel_imports = [i for i in imports if not i.startswith(".")][:8]
    exposed = [s.name for s in symbols][:8]

    parts = [f"Language: {language.capitalize()}"]
    if exposed:
        parts.append(f"Exposes: {', '.join(exposed)}")
    if rel_imports:
        parts.append(f"Imports: {', '.join(rel_imports)}")
    parts.append(f"Likely responsibility: {_infer_responsibility(path, exposed)}")

    return FileSummary(
        path=path,
        hash=file_hash,
        language=language,
        provider="offline",
        schema_version=1,
        summary="\n- ".join([""] + parts).lstrip("\n- ") if parts else "",
        imports=imports[:20],
        symbols=symbols,
    )


def _generic_summary(path: str, abs_path: Path, language: str | None, file_hash: str) -> FileSummary:
    try:
        lines = abs_path.read_text(errors="replace").splitlines()[:30]
        snippet = "\n".join(lines)
    except OSError:
        snippet = ""

    return FileSummary(
        path=path,
        hash=file_hash,
        language=language,
        provider="offline",
        schema_version=1,
        summary=f"Language: {language or 'unknown'}\nFirst lines:\n{snippet[:300]}",
        imports=[],
        symbols=[],
    )


_SEMANTIC_PATTERNS = [
    ({"test", "spec", "fixture"}, {"test_", "spec_", "fixture_"}, "tests"),
    ({"auth", "login", "token", "session", "jwt"}, {"authenticate", "authorize", "login", "logout", "token"}, "authentication / authorization"),
    ({"cache", "redis", "memcache"}, {"cache", "invalidate", "ttl", "expire"}, "caching layer"),
    ({"model", "schema", "entity"}, {"BaseModel", "Model", "Schema", "dataclass"}, "data models / schema"),
    ({"migrate", "migration", "alembic", "flyway"}, set(), "database migrations"),
    ({"route", "router", "endpoint", "view", "handler", "controller"}, {"get", "post", "put", "delete", "patch", "handle", "dispatch"}, "request routing / handlers"),
    ({"config", "setting", "env"}, {"load_config", "Config", "Settings"}, "configuration"),
    ({"cli", "command", "cmd"}, {"main", "cli", "command", "run"}, "CLI entry point"),
    ({"scan", "parse", "extract", "analyze"}, {"scan", "parse", "extract", "analyze", "build"}, "analysis / parsing"),
    ({"render", "format", "template", "serializ"}, {"render", "format", "serialize", "template"}, "rendering / formatting"),
    ({"deploy", "ci", "docker", "k8s", "workflow"}, set(), "deployment / CI"),
    ({"util", "helper", "tool", "common", "shared"}, set(), "utilities / helpers"),
    ({"payment", "billing", "invoice", "stripe", "checkout"}, {"charge", "pay", "invoice", "refund", "subscription"}, "payments / billing"),
    ({"email", "mail", "smtp", "sendgrid", "mailgun", "notification"}, {"send_email", "send_mail", "notify", "alert"}, "email / notifications"),
    ({"queue", "worker", "job", "task", "celery", "rq", "sidekiq", "kafka", "rabbit"}, {"enqueue", "dequeue", "consume", "publish", "process_job"}, "background jobs / queues"),
    ({"websocket", "ws", "socket", "realtime", "sse", "stream"}, {"broadcast", "emit", "subscribe", "on_message"}, "realtime / websockets"),
    ({"search", "index", "elastic", "solr", "lucene", "vector", "embed"}, {"search", "index_doc", "query", "reindex"}, "search / indexing"),
    ({"storage", "s3", "gcs", "blob", "bucket", "upload", "download", "file"}, {"upload", "download", "put_object", "get_object", "store"}, "file storage"),
    ({"metric", "monitor", "trace", "telemetry", "otel", "prometheus", "sentry", "datadog"}, {"record_metric", "trace", "span", "counter", "gauge"}, "observability / metrics"),
    ({"permission", "role", "rbac", "acl", "policy", "access"}, {"check_permission", "has_role", "is_allowed", "enforce"}, "authorization / RBAC"),
    ({"rate", "throttle", "limit", "quota", "ratelimit"}, {"throttle", "rate_limit", "check_quota"}, "rate limiting"),
    ({"seed", "factory", "fake", "mock", "stub"}, {"create_", "build_", "make_", "factory", "seed"}, "test data / factories"),
    ({"admin", "dashboard", "panel", "backoffice"}, {"admin_", "register_", "site"}, "admin / dashboard"),
    ({"report", "export", "csv", "pdf", "excel", "xlsx"}, {"generate_report", "export_csv", "to_pdf"}, "reporting / exports"),
    ({"hook", "webhook", "event", "signal", "dispatch", "listener"}, {"on_", "handle_", "dispatch", "emit", "signal"}, "events / webhooks"),
    ({"validate", "validator", "form", "serializer"}, {"validate", "is_valid", "clean", "deserialize"}, "validation / serialization"),
    ({"crypto", "encrypt", "decrypt", "hash", "sign", "verify", "hmac", "aes", "rsa"}, {"encrypt", "decrypt", "hash_", "sign", "verify"}, "cryptography"),
    ({"log", "logging", "logger", "audit", "trail"}, {"log_", "audit_", "get_logger"}, "logging / audit"),
    ({"batch", "bulk", "import", "etl", "ingest", "pipeline"}, {"batch_", "bulk_", "ingest", "process_batch"}, "data pipeline / ETL"),
    ({"health", "ping", "status", "ready", "live"}, {"healthcheck", "ping", "is_ready", "is_alive"}, "health checks"),
    ({"retry", "backoff", "circuit", "breaker", "fault"}, {"retry", "with_retry", "backoff", "circuit_breaker"}, "resilience / retry"),
    ({"i18n", "locale", "translation", "l10n", "gettext", "language"}, {"translate", "gettext", "_", "ngettext"}, "i18n / localization"),
    ({"proxy", "gateway", "load", "balancer", "upstream", "downstream"}, {"forward", "proxy_pass", "route_request"}, "proxy / gateway"),
    ({"sourcing", "cqrs", "aggregate", "projection"}, {"apply_event", "handle_command", "project", "aggregate"}, "event sourcing / CQRS"),
    ({"graph", "node", "edge", "tree", "traverse", "walk"}, {"traverse", "dfs", "bfs", "walk_tree"}, "graph / tree traversal"),
    ({"client", "sdk", "fetch"}, {"get", "post", "fetch", "request", "call_api"}, "API client"),
    ({"lock", "mutex", "semaphore", "concurrent", "thread"}, {"acquire", "release", "lock", "asyncio", "await"}, "concurrency / locking"),
    ({"snapshot", "backup", "restore", "archive"}, {"snapshot", "backup", "restore", "archive"}, "snapshots / backup"),
    ({"diff", "patch", "merge", "conflict", "delta"}, {"diff", "patch", "merge", "apply_patch"}, "diff / merge"),
    ({"plugin", "extension", "addon", "middleware"}, {"register_plugin", "use_middleware", "extend"}, "plugins / middleware"),
]


def _infer_responsibility(path: str, symbols: list[str]) -> str:
    segments = re.split(r"[/_\-.]", path.lower())
    segments_set = set(segments)
    bigrams = {f"{segments[i]}_{segments[i + 1]}" for i in range(len(segments) - 1)}
    bigrams |= {f"{segments[i]}{segments[i + 1]}" for i in range(len(segments) - 1)}
    all_path_tokens = segments_set | bigrams
    symbols_lower = [s.lower() for s in symbols]
    for path_kw, sym_kw, label in _SEMANTIC_PATTERNS:
        if any(tok for tok in all_path_tokens if any(kw in tok for kw in path_kw)):
            return label
        if sym_kw and any(kw.lower() in sym for sym in symbols_lower for kw in sym_kw):
            return label
    return Path(path).stem.replace("_", " ")
