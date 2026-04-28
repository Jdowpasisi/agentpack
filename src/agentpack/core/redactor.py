from __future__ import annotations

import re

# Placeholder patterns — values matching these are NOT redacted
_PLACEHOLDER_RE = re.compile(
    r"your[_-]?(?:api[_-]?)?(?:key|token|secret)[_-]?here|"
    r"<[A-Z_]{3,}(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*>|"
    r"xxx+|"
    r"insert[_-]?(?:key|token|secret)[_-]?here|"
    r"changeme|"
    r"example[_-]?(?:key|token|secret)|"
    r"(?:key|token|secret)[_-]?example",
    re.IGNORECASE,
)

# (pattern, label, value_group): when value_group is set, only that group is redacted.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str, int | None]] = [
    (re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ), "private-key", None),
    (re.compile(
        r"eyJ[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}"
    ), "jwt", None),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws-access-key", None),
    (re.compile(
        r"(?i)(aws_secret(?:_access_key)?\s*[=:\"'\s]+\s*)([A-Za-z0-9+/]{40})"
    ), "aws-secret-key", 2),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "github-token", None),
    # Anthropic before OpenAI to avoid partial match on sk- prefix
    (re.compile(r"sk-ant-[A-Za-z0-9\-]{32,}"), "anthropic-key", None),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "openai-key", None),
    # Generic: handles key=value, key='value', key="value", key: value
    (re.compile(
        r"(?i)(?:api[_-]?key|token|secret|password|passwd|auth[_-]?key)"
        r"\s*[=:]\s*[\"']?\s*([A-Za-z0-9+/\-_]{40,})"
    ), "api-key", 1),
]


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


def _line_of(text: str, start: int) -> int:
    """Return 1-indexed line number for character offset *start* in *text*."""
    return text.count("\n", 0, start) + 1


def redact_secrets(text: str, path: str) -> tuple[str, list[str]]:
    """Scan *text* for secrets and replace each with ``[REDACTED:<type>]``.

    Returns ``(redacted_text, warnings)`` where each warning is a
    human-readable string like ``"src/config.py: aws-access-key detected (line 12)"``.
    """
    warnings: list[str] = []
    # Collect (start, end, replacement_str) tuples; apply in reverse order.
    replacements: list[tuple[int, int, str]] = []
    # Track redacted spans to avoid double-reporting overlapping matches.
    redacted_spans: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        for rs, re_ in redacted_spans:
            if start < re_ and end > rs:
                return True
        return False

    for pattern, label, value_group in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            if value_group is not None:
                secret_val = m.group(value_group)
                secret_start = m.start(value_group)
                secret_end = m.end(value_group)
            else:
                secret_val = m.group(0)
                secret_start = m.start()
                secret_end = m.end()

            if _is_placeholder(secret_val):
                continue
            if _overlaps(secret_start, secret_end):
                continue

            line_no = _line_of(text, secret_start)
            replacements.append((secret_start, secret_end, f"[REDACTED:{label}]"))
            redacted_spans.append((secret_start, secret_end))
            warnings.append(f"{path}: {label} detected (line {line_no})")

    if not replacements:
        return text, warnings

    # Apply replacements in reverse order to preserve earlier offsets
    replacements.sort(key=lambda r: r[0], reverse=True)
    chars = list(text)
    for start, end, repl in replacements:
        chars[start:end] = list(repl)

    return "".join(chars), warnings
