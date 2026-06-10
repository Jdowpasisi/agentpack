from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from agentpack.analysis.python_ast import parse_python_source
from agentpack.core.models import Symbol


@dataclass
class RoleInferenceResult:
    domain: str | None
    role: str | None
    ranking_keywords: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class CodeIntelligence:
    entrypoints: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class SideEffectInfo:
    reads_env: list[str] = field(default_factory=list)
    reads_files: list[str] = field(default_factory=list)
    writes_files: list[str] = field(default_factory=list)
    external_systems: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "all"}


def infer_role_domain(
    *,
    path: str,
    language: str | None,
    symbols: list[Symbol],
    imports: list[str],
    text: str,
    entrypoints: list[str] | None = None,
    external_systems: list[str] | None = None,
) -> RoleInferenceResult:
    """Infer coarse domain/role from deterministic, explainable signals."""
    entrypoints = entrypoints or []
    external_systems = external_systems or []
    path_tokens = _path_tokens(path)
    symbol_tokens = _tokens(" ".join(s.name for s in symbols))
    import_tokens = _tokens(" ".join(imports))
    entrypoint_tokens = _tokens(" ".join(entrypoints))
    text_tokens = _tokens(text[:4000])
    all_tokens = path_tokens | symbol_tokens | import_tokens | entrypoint_tokens | text_tokens

    domain_scores: dict[str, float] = defaultdict(float)
    role_scores: dict[str, float] = defaultdict(float)
    reasons: list[str] = []

    def score_domain(name: str, amount: float, reason: str) -> None:
        domain_scores[name] += amount
        reasons.append(reason)

    def score_role(name: str, amount: float, reason: str) -> None:
        role_scores[name] += amount
        reasons.append(reason)

    if path_tokens & {"auth", "login", "session", "jwt", "token", "otp"}:
        score_domain("auth", 3.0, "path suggests auth")
    if import_tokens & {"jwt", "jose", "passport", "nextauth"}:
        score_domain("auth", 2.0, "imports auth library")
    if "otp" in all_tokens:
        score_domain("otp/auth", 4.0, "OTP signal")
    if path_tokens & {"payment", "payments", "billing", "invoice", "checkout", "stripe"}:
        score_domain("payments", 3.0, "path suggests payments")
    if import_tokens & {"stripe"} or "Stripe" in external_systems:
        score_domain("payments", 3.0, "Stripe signal")
    if path_tokens & {"email", "mail", "mailer", "notification", "notifications"}:
        score_domain("notifications", 3.0, "path suggests notifications")
    if import_tokens & {"smtplib", "sendgrid", "mailgun"}:
        score_domain("notifications", 2.0, "email provider import")
    if path_tokens & {"cache", "redis"} or "Redis" in external_systems:
        score_domain("cache", 3.0, "cache/Redis signal")
    if path_tokens & {"model", "models", "schema", "db", "database", "repository"}:
        score_domain("data", 2.0, "path suggests data layer")
    if any(system in external_systems for system in ("PostgreSQL/Django ORM", "SQLAlchemy", "Prisma", "MongoDB/Mongoose")):
        score_domain("data", 2.0, "database system signal")
    if path_tokens & {"component", "components", "page", "pages", "layout", "frontend"} or path.endswith((".tsx", ".jsx")):
        score_domain("frontend", 2.0, "frontend path/component signal")
    if path_tokens & {"api", "route", "routes", "router", "view", "views", "controller"} or entrypoints:
        score_domain("api", 1.5, "API route signal")
    if path_tokens & {"task", "tasks", "job", "jobs", "worker", "workers"}:
        score_domain("jobs", 2.0, "background job path")
    if path_tokens & {"summary", "summaries", "rank", "ranking", "repo", "context", "pack"}:
        score_domain("context packing", 2.0, "AgentPack context/summarization signal")

    owner_tokens = path_tokens | symbol_tokens | import_tokens
    if ("frontend" in domain_scores and "auth" in domain_scores) or (
        path_tokens & {"component", "components", "page", "pages"}
        and (path_tokens | symbol_tokens) & {"login", "auth", "session", "signin"}
    ):
        score_domain("frontend/auth", 4.0, "frontend auth signal")

    route_entrypoints = [ep for ep in entrypoints if re.match(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|ALL)\s+", ep)]
    if route_entrypoints:
        if "otp" in all_tokens and "verify" in all_tokens:
            score_role("OTP verification API route", 7.0, "OTP verify route")
        elif "stripe" in all_tokens and "webhook" in all_tokens:
            score_role("Stripe webhook handling", 7.0, "Stripe webhook route")
        elif "webhook" in all_tokens:
            score_role("webhook handler", 5.0, "webhook route")
        else:
            score_role("HTTP API route handler", 4.0, "HTTP route decorator/call")

    if any(ep.startswith("Django URL:") for ep in entrypoints):
        score_role("Django URL routing", 5.0, "Django url pattern")
    if any(ep.startswith("Django view:") for ep in entrypoints):
        score_role("Django view handler", 4.0, "Django view class/function")
    if any(ep.startswith("Django management command:") for ep in entrypoints):
        score_role("Django management command", 6.0, "management command path")
    if any(ep.startswith("Celery task:") for ep in entrypoints):
        if all_tokens & {"email", "mail", "send", "notify", "notification"}:
            score_role("background email task", 7.0, "Celery email task")
        else:
            score_role("background task", 5.0, "Celery task")
    if any(ep.startswith("CLI command:") for ep in entrypoints):
        score_role("CLI command", 5.0, "CLI command decorator")
    if any(ep.startswith("Next API route:") for ep in entrypoints):
        score_role("Next.js API route", 5.0, "Next.js route file")
    if any(ep.startswith("React page:") for ep in entrypoints):
        score_role("React page component", 4.0, "Next/React page")
    if any(ep.startswith("React component:") for ep in entrypoints):
        if all_tokens & {"login", "signin"}:
            score_role("login form UI component", 7.0, "login component")
        else:
            score_role("React UI component", 4.0, "React component")

    if owner_tokens & {"session", "jwt", "token"} and not route_entrypoints:
        score_role("session/token management", 5.0, "session/token symbols")
    if all_tokens & {"summary", "summarize", "summaries"}:
        score_role("offline file summary generation", 4.0, "summary symbols/path")
    if all_tokens & {"ranking", "rank", "score", "selection"}:
        score_role("context ranking and selection", 4.0, "ranking symbols/path")
    if all_tokens & {"repo", "map"} and "repo_map" in path.replace("/", "_"):
        score_role("repo map generation", 4.0, "repo map path")
    if all_tokens & {"config", "settings", "env"}:
        score_role("configuration", 2.0, "config/env signal")

    domain = _best(domain_scores)
    role = _best(role_scores) or _fallback_role(path, symbols, entrypoints)
    ranking_keywords = _ranking_keywords(path, domain, role, symbols, imports, entrypoints, external_systems)
    return RoleInferenceResult(
        domain=domain,
        role=role,
        ranking_keywords=ranking_keywords,
        reasons=_dedupe(reasons)[:12],
    )


def extract_code_intelligence(
    *,
    path: str,
    language: str | None,
    text: str,
    symbols: list[Symbol],
) -> CodeIntelligence:
    if language == "python":
        return _python_intelligence(path, text, symbols)
    if language in {"javascript", "typescript"}:
        return _js_ts_intelligence(path, text, symbols)
    return CodeIntelligence(defines=[s.name for s in symbols[:40]])


def extract_side_effects(
    *,
    path: str,
    language: str | None,
    text: str,
    imports: list[str],
) -> SideEffectInfo:
    haystack = f"{path}\n{text}\n{' '.join(imports)}"
    lower = haystack.lower()
    reads_env = _extract_env_reads(text)
    reads_files, writes_files = _extract_file_access(text)
    external_systems = _extract_external_systems(lower, imports)

    side_effects: list[str] = []
    if reads_env:
        side_effects.append("reads environment/config")
    if reads_files:
        side_effects.append("possible filesystem read")
    if writes_files:
        side_effects.append("possible filesystem write")
    if "Redis" in external_systems:
        side_effects.append("possible Redis read/write")
    if "S3" in external_systems:
        side_effects.append("possible S3 usage")
    if any(system in external_systems for system in ("SQS", "SNS", "Kafka", "Celery")):
        side_effects.append("possible queue/task dispatch")
    if "HTTP" in external_systems:
        side_effects.append("possible HTTP call")
    if any(system in external_systems for system in ("PostgreSQL/Django ORM", "SQLAlchemy", "Prisma", "MongoDB/Mongoose")):
        side_effects.append("possible DB access")
    if "SMTP/email" in external_systems:
        side_effects.append("possible email send")
    if any(system in external_systems for system in ("Sentry", "Datadog", "CloudWatch/logging")):
        side_effects.append("possible observability/logging")
    if re.search(r"\b(subprocess|popen\(|exec\(|spawn\()", lower):
        side_effects.append("subprocess")
    if re.search(r"\b(print\(|logger\.|logging\.|console\.)", lower):
        side_effects.append("logging")

    return SideEffectInfo(
        reads_env=_dedupe(reads_env)[:20],
        reads_files=_dedupe(reads_files)[:20],
        writes_files=_dedupe(writes_files)[:20],
        external_systems=_dedupe(external_systems)[:20],
        side_effects=_dedupe(side_effects)[:12],
    )


def extract_failure_hints(text: str) -> list[str]:
    checks = [
        ("raises exceptions", (r"\braise\s+\w+", r"\bthrow\s+new\b")),
        ("catches exceptions", (r"\bexcept\b", r"\bcatch\s*\(")),
        ("exits process", (r"typer\.Exit", r"sys\.exit", r"process\.exit")),
        ("returns error responses", (r"HTTPException", r"status_code\s*=\s*[45]\d\d", r"Response\(")),
        ("logs errors", (r"\.exception\(", r"\.error\(")),
    ]
    found: list[str] = []
    for label, patterns in checks:
        if any(re.search(pattern, text) for pattern in patterns):
            found.append(label)
    return found


def _python_intelligence(path: str, text: str, symbols: list[Symbol]) -> CodeIntelligence:
    try:
        tree = parse_python_source(text, path)
    except SyntaxError:
        return CodeIntelligence(defines=[s.name for s in symbols[:40]])

    entrypoints: list[str] = []
    defines: list[str] = []
    calls: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            defines.append(node.name)
            if _inherits_view(node):
                entrypoints.append(f"Django view: {node.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defines.append(node.name)
            for dec in node.decorator_list:
                dec_name = _expr_name(dec)
                route = _route_from_decorator(dec)
                if route:
                    entrypoints.append(route)
                elif dec_name == "shared_task" or dec_name.endswith(".task"):
                    entrypoints.append(f"Celery task: {node.name}")
                elif dec_name.endswith(".command") or dec_name == "click.command":
                    entrypoints.append(f"CLI command: {_decorator_command_name(dec, node.name)}")
        elif isinstance(node, ast.Call):
            call_name = _expr_name(node.func)
            if call_name:
                calls.append(call_name)
            url_entry = _django_url_entrypoint(node)
            if url_entry:
                entrypoints.append(url_entry)

    if "/management/commands/" in path.replace("\\", "/"):
        command_name = Path(path).stem
        if "Command" in defines:
            entrypoints.append(f"Django management command: {command_name}")

    return CodeIntelligence(
        entrypoints=_dedupe(entrypoints)[:40],
        defines=_dedupe(defines or [s.name for s in symbols])[:60],
        calls=_dedupe(calls)[:80],
    )


def _js_ts_intelligence(path: str, text: str, symbols: list[Symbol]) -> CodeIntelligence:
    entrypoints: list[str] = []
    defines = [s.name for s in symbols]

    for method, route in re.findall(
        r"\b(?:router|app)\.(get|post|put|patch|delete|options|head|all)\s*\(\s*['\"]([^'\"]+)['\"]",
        text,
        flags=re.IGNORECASE,
    ):
        entrypoints.append(f"{method.upper()} {route}")

    norm_path = path.replace("\\", "/")
    if re.search(r"(?:^|/)app/api/.*/route\.(?:ts|tsx|js|jsx)$", norm_path):
        api_path = _next_api_path(norm_path)
        methods = re.findall(r"\bexport\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\(", text)
        if methods:
            for method in methods:
                entrypoints.append(f"{method} {api_path}")
        entrypoints.append(f"Next API route: {norm_path}")
    if re.search(r"(?:^|/)pages/api/.*\.(?:ts|tsx|js|jsx)$", norm_path):
        entrypoints.append(f"Next API route: {norm_path}")
    if re.search(r"(?:^|/)app/.*/page\.(?:tsx|jsx|ts|js)$", norm_path) or re.search(
        r"(?:^|/)pages/.*\.(?:tsx|jsx|ts|js)$", norm_path
    ):
        entrypoints.append(f"React page: {norm_path}")
    if re.search(r"(?:^|/)app/.*/layout\.(?:tsx|jsx|ts|js)$", norm_path):
        entrypoints.append(f"React layout: {norm_path}")

    for name in re.findall(
        r"\b(?:export\s+default\s+)?function\s+([A-Z][A-Za-z0-9_]*)\s*\(|\b(?:export\s+)?const\s+([A-Z][A-Za-z0-9_]*)\s*=\s*(?:\([^)]*\)|\w+)\s*=>",
        text,
    ):
        component = name[0] or name[1]
        entrypoints.append(f"React component: {component}")
        defines.append(component)

    if text.startswith("#!") and "node" in text.splitlines()[0]:
        entrypoints.append(f"CLI script: {norm_path}")

    calls = _js_calls(text)
    return CodeIntelligence(
        entrypoints=_dedupe(entrypoints)[:40],
        defines=_dedupe(defines)[:60],
        calls=_dedupe(calls)[:80],
    )


def _route_from_decorator(dec: ast.expr) -> str | None:
    if not isinstance(dec, ast.Call):
        return None
    name = _expr_name(dec.func)
    method = name.rsplit(".", 1)[-1].lower()
    if method not in HTTP_METHODS:
        return None
    base = name.rsplit(".", 1)[0]
    if base.split(".")[-1] not in {"app", "router"}:
        return None
    route = _literal_arg(dec, 0) or ""
    return f"{method.upper()} {route or '<dynamic route>'}"


def _django_url_entrypoint(node: ast.Call) -> str | None:
    name = _expr_name(node.func)
    if name not in {"path", "re_path", "django.urls.path", "django.urls.re_path"}:
        return None
    route = _literal_arg(node, 0) or "<dynamic route>"
    target = _expr_name(node.args[1]) if len(node.args) > 1 else ""
    return f"Django URL: {route}" + (f" -> {target}" if target else "")


def _decorator_command_name(dec: ast.expr, fallback: str) -> str:
    if isinstance(dec, ast.Call):
        literal = _literal_arg(dec, 0)
        if literal:
            return literal
        for keyword in dec.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
    return fallback.replace("_", "-")


def _inherits_view(node: ast.ClassDef) -> bool:
    suffixes = ("View", "APIView", "ViewSet", "GenericViewSet", "ModelViewSet")
    for base in node.bases:
        name = _expr_name(base)
        if name.endswith(suffixes):
            return True
    return False


def _literal_arg(call: ast.Call, index: int) -> str | None:
    if len(call.args) <= index:
        return None
    arg = call.args[index]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _expr_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ""


def _extract_env_reads(text: str) -> list[str]:
    keys: list[str] = []
    patterns = [
        r"os\.environ\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]",
        r"os\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"\bgetenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)",
        r"process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]",
        r"\bconfig\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_.-]*)['\"]",
    ]
    for pattern in patterns:
        keys.extend(re.findall(pattern, text))
    for prefix in ("settings", "config"):
        for key in re.findall(rf"\b{prefix}\.([A-Z][A-Z0-9_]*)", text):
            keys.append(key)
    return keys


def _extract_file_access(text: str) -> tuple[list[str], list[str]]:
    reads: list[str] = []
    writes: list[str] = []

    for path_expr, mode in re.findall(
        r"\bopen\(\s*([^,\)]+)(?:,\s*['\"]([^'\"]*)['\"])?",
        text,
    ):
        label = _clean_path_expr(path_expr)
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            writes.append(label)
        else:
            reads.append(label)

    for path_expr in re.findall(r"Path\(([^)]*)\)\.read_text\(", text):
        reads.append(_clean_path_expr(path_expr))
    for path_expr in re.findall(r"Path\(([^)]*)\)\.write_text\(", text):
        writes.append(_clean_path_expr(path_expr))
    for path_expr in re.findall(r"\bfs\.(?:readFileSync|readFile|createReadStream)\(\s*([^,\)]+)", text):
        reads.append(_clean_path_expr(path_expr))
    for path_expr in re.findall(r"\bfs\.(?:writeFileSync|writeFile|appendFile|createWriteStream)\(\s*([^,\)]+)", text):
        writes.append(_clean_path_expr(path_expr))
    return reads, writes


def _clean_path_expr(value: str) -> str:
    value = value.strip()
    if re.match(r"^['\"][^'\"]+['\"]$", value):
        return value.strip("'\"")
    return "dynamic path"


def _extract_external_systems(lower: str, imports: list[str]) -> list[str]:
    import_text = " ".join(imports).lower()
    combined = f"{lower}\n{import_text}"
    systems: list[str] = []
    checks = [
        ("Redis", (r"\bredis\b", r"ioredis")),
        ("Celery", (r"\bcelery\b", r"shared_task", r"\.delay\(")),
        ("Kafka", (r"\bkafka\b", r"confluent_kafka")),
        ("S3", (r"\bs3\b", r"put_object", r"get_object", r"boto3\.client\(['\"]s3")),
        ("SQS", (r"\bsqs\b", r"send_message", r"receive_message")),
        ("SNS", (r"\bsns\b", r"publish\(")),
        ("DynamoDB", (r"dynamodb",)),
        ("HTTP", (r"\brequests\b", r"\bhttpx\b", r"\baiohttp\b", r"\burllib\b", r"\bfetch\(", r"\baxios\b")),
        ("Stripe", (r"\bstripe\b",)),
        ("OpenAI API", (r"\bopenai\b",)),
        ("Anthropic API", (r"\banthropic\b",)),
        ("Google API", (r"googleapiclient", r"google\.cloud", r"\bgapi\b")),
        ("SQLAlchemy", (r"sqlalchemy", r"session\.query", r"select\(")),
        ("PostgreSQL/Django ORM", (r"django\.db", r"\.objects\.", r"psycopg", r"postgres", r"cursor\.execute")),
        ("Prisma", (r"\bprisma\b",)),
        ("MongoDB/Mongoose", (r"\bmongoose\b", r"\bpymongo\b", r"mongodb")),
        ("SMTP/email", (r"\bsmtplib\b", r"\bsmtp\b", r"send_mail", r"send_email", r"sendgrid", r"mailgun")),
        ("Sentry", (r"\bsentry_sdk\b", r"\bsentry\b")),
        ("Datadog", (r"\bdatadog\b", r"\bddtrace\b")),
        ("CloudWatch/logging", (r"cloudwatch", r"\blogging\b", r"logger\.")),
    ]
    for name, patterns in checks:
        if any(re.search(pattern, combined) for pattern in patterns):
            systems.append(name)
    return systems


def _js_calls(text: str) -> list[str]:
    skip = {
        "if", "for", "while", "switch", "catch", "function", "return",
        "typeof", "new", "class", "super", "import", "export",
    }
    calls: list[str] = []
    for name in re.findall(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", text):
        if name.split(".")[0] not in skip:
            calls.append(name)
    return calls


def _next_api_path(path: str) -> str:
    match = re.search(r"(?:^|/)app/api/(.*)/route\.(?:ts|tsx|js|jsx)$", path)
    if not match:
        return "/api"
    return "/api/" + match.group(1).strip("/")


def _best(scores: dict[str, float]) -> str | None:
    if not scores:
        return None
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _fallback_role(path: str, symbols: list[Symbol], entrypoints: list[str]) -> str:
    stem = Path(path).stem.replace("_", " ").replace("-", " ")
    if entrypoints:
        return "entrypoint"
    if any(s.kind == "class" for s in symbols):
        return f"{stem} classes"
    if any(s.kind == "function" for s in symbols):
        return f"{stem} functions"
    return stem


def _ranking_keywords(
    path: str,
    domain: str | None,
    role: str | None,
    symbols: list[Symbol],
    imports: list[str],
    entrypoints: list[str],
    external_systems: list[str],
) -> list[str]:
    keywords: list[str] = []
    for text in [domain or "", role or "", " ".join(entrypoints), " ".join(external_systems)]:
        keywords.extend(sorted(_tokens(text)))
    for sym in symbols[:20]:
        keywords.extend(sorted(_tokens(sym.name)))
    noise = {
        "src", "app", "lib", "api", "py", "ts", "tsx", "js", "jsx",
        "route", "routes", "handler", "http", "component", "page", "fixtures", "tests",
        "fastapi", "django", "react", "nextjs", "router", "request", "response",
    }
    return [kw for kw in _dedupe(keywords) if len(kw) >= 3 and kw not in noise][:30]


def _path_tokens(path: str) -> set[str]:
    return _tokens(path)


def _tokens(text: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw = re.split(r"[^A-Za-z0-9]+", spaced.lower())
    return {part for part in raw if part}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
