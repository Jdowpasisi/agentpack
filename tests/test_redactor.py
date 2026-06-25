"""Tests for agentpack.core.redactor."""
from __future__ import annotations


from agentpack.core.redactor import redact_secrets


# ---------------------------------------------------------------------------
# AWS access key
# ---------------------------------------------------------------------------

def test_aws_access_key_detected():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = f"key = {key}"
    result, warnings = redact_secrets(text, "src/config.py")
    assert "[REDACTED:aws-access-key]" in result
    assert "AKIA" not in result

def test_aws_access_key_warning_format():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = f"key = {key}"
    _, warnings = redact_secrets(text, "src/config.py")
    assert len(warnings) == 1
    assert "src/config.py" in warnings[0]
    assert "aws-access-key" in warnings[0]
    assert "line 1" in warnings[0]

def test_aws_access_key_surrounding_text_preserved():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = f"export AWS_ACCESS_KEY_ID={key}\n# end"
    result, _ = redact_secrets(text, "f.py")
    assert "export AWS_ACCESS_KEY_ID=" in result
    assert "# end" in result


# ---------------------------------------------------------------------------
# AWS secret key
# ---------------------------------------------------------------------------

def test_aws_secret_key_detected():
    # Exactly 40 base64 chars (real AWS secret key length); no placeholder words
    secret = "".join(["aB3dEfGhIjKlMnOpQrStUvWxYz", "0123456789+/AB"])
    text = f"aws_secret_access_key = {secret}"
    result, warnings = redact_secrets(text, "creds.py")
    assert "[REDACTED:aws-secret-key]" in result
    assert secret not in result
    assert "aws_secret_access_key" in result  # key name preserved

def test_aws_secret_key_warning_line_number():
    secret = "".join(["aB3dEfGhIjKlMnOpQrStUvWxYz", "0123456789+/AB"])
    text = f"# header\naws_secret = {secret}\n"
    _, warnings = redact_secrets(text, "a.py")
    assert any("line 2" in w for w in warnings)


# ---------------------------------------------------------------------------
# GitHub tokens
# ---------------------------------------------------------------------------

def test_github_personal_access_token():
    token = "ghp_" + "A" * 36
    text = f"GITHUB_TOKEN={token}"
    result, warnings = redact_secrets(text, "env.sh")
    assert "[REDACTED:github-token]" in result
    assert token not in result
    assert any("github-token" in w for w in warnings)

def test_github_oauth_token():
    token = "gho_" + "B" * 40
    text = f"token: {token}"
    result, warnings = redact_secrets(text, "config.yaml")
    assert "[REDACTED:github-token]" in result

def test_github_server_token():
    token = "ghs_" + "C" * 36
    _, warnings = redact_secrets(token, "f.py")
    assert any("github-token" in w for w in warnings)

def test_github_user_token():
    token = "ghu_" + "D" * 36
    _, warnings = redact_secrets(token, "f.py")
    assert any("github-token" in w for w in warnings)

def test_github_refresh_token():
    token = "ghr_" + "E" * 36
    _, warnings = redact_secrets(token, "f.py")
    assert any("github-token" in w for w in warnings)


# ---------------------------------------------------------------------------
# OpenAI keys
# ---------------------------------------------------------------------------

def test_openai_key_detected():
    key = "sk-" + ("a" * 48)
    text = f"OPENAI_API_KEY={key}"
    result, warnings = redact_secrets(text, "settings.py")
    assert "[REDACTED:openai-key]" in result
    assert key not in result
    assert any("openai-key" in w for w in warnings)

def test_openai_key_line_number():
    key = "sk-" + ("b" * 48)
    text = f"line1\nline2\nOPENAI={key}"
    _, warnings = redact_secrets(text, "x.py")
    assert any("line 3" in w for w in warnings)


# ---------------------------------------------------------------------------
# Anthropic keys
# ---------------------------------------------------------------------------

def test_anthropic_key_detected():
    key = "".join(["sk-ant-api03-", "z" * 32])
    text = f"ANTHROPIC_API_KEY={key}"
    result, warnings = redact_secrets(text, "app.py")
    assert "[REDACTED:anthropic-key]" in result
    assert key not in result
    assert any("anthropic-key" in w for w in warnings)

def test_anthropic_key_with_dashes():
    key = "sk-ant-" + "A-b" * 15  # 45 chars after prefix
    _, warnings = redact_secrets(key, "f.py")
    assert any("anthropic-key" in w for w in warnings)


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

def test_jwt_detected():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"Authorization: Bearer {jwt}"
    result, warnings = redact_secrets(text, "middleware.py")
    assert "[REDACTED:jwt]" in result
    assert "eyJ" not in result
    assert any("jwt" in w for w in warnings)

def test_jwt_warning_includes_line():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"# comment\ntoken = {jwt}"
    _, warnings = redact_secrets(text, "mod.py")
    assert any("line 2" in w for w in warnings)


# ---------------------------------------------------------------------------
# Private key blocks
# ---------------------------------------------------------------------------

def test_rsa_private_key_block():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    text = f"# key\n{block}\n"
    result, warnings = redact_secrets(text, "key.pem")
    assert "[REDACTED:private-key]" in result
    assert "BEGIN RSA PRIVATE KEY" not in result
    assert any("private-key" in w for w in warnings)

def test_openssh_private_key_block():
    block = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA...\n-----END OPENSSH PRIVATE KEY-----"
    result, warnings = redact_secrets(block, "id_rsa")
    assert "[REDACTED:private-key]" in result

def test_generic_private_key_block():
    block = "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----"
    result, warnings = redact_secrets(block, "key.pem")
    assert "[REDACTED:private-key]" in result


# ---------------------------------------------------------------------------
# Generic high-entropy token near assignment keyword
# ---------------------------------------------------------------------------

def test_generic_token_near_token_keyword():
    secret = "".join(["a1b2c3d4e5f6a1b2c3d4", "e5f6a1b2c3d4e5f6a1b2"])  # 40 hex chars
    text = f"token={secret}"
    result, warnings = redact_secrets(text, "cfg.py")
    assert "[REDACTED:api-key]" in result
    assert secret not in result

def test_generic_secret_near_password_keyword():
    secret = "".join(["SuperSecretPassword12345", "678901234567890xyz"])  # >40 chars
    text = f"password = {secret}"
    result, warnings = redact_secrets(text, "db.py")
    assert "[REDACTED:api-key]" in result

def test_generic_key_assignment():
    secret = ("abc123" * 7)[:41]
    text = "api_" + "key = '" + secret + "'"
    result, warnings = redact_secrets(text, "app.py")
    assert "[REDACTED:api-key]" in result
    assert "api_key" in result  # key name preserved


# ---------------------------------------------------------------------------
# Placeholder values NOT redacted
# ---------------------------------------------------------------------------

def test_placeholder_your_api_key_here_not_redacted():
    text = "api_key = your-api-key-here"
    result, warnings = redact_secrets(text, "example.py")
    assert "your-api-key-here" in result
    assert not warnings

def test_placeholder_angle_bracket_not_redacted():
    text = "token = <YOUR_TOKEN_HERE>"
    result, warnings = redact_secrets(text, "readme.py")
    assert "<YOUR_TOKEN_HERE>" in result
    assert not warnings

def test_placeholder_xxx_not_redacted():
    text = "password = " + ("xxxx" * 10)
    result, warnings = redact_secrets(text, "test.py")
    assert not warnings

def test_placeholder_changeme_not_redacted():
    text = "secret = changeme"
    result, warnings = redact_secrets(text, "test.py")
    assert "changeme" in result
    assert not warnings


# ---------------------------------------------------------------------------
# Warning format
# ---------------------------------------------------------------------------

def test_warning_format_path_type_line():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = f"k = {key}"
    _, warnings = redact_secrets(text, "src/config.py")
    assert len(warnings) == 1
    w = warnings[0]
    assert w.startswith("src/config.py: ")
    assert "aws-access-key" in w
    assert "(line 1)" in w

def test_warning_multiline_correct_line():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = "a = 1\nb = 2\nc = 3\nkey = " + key
    _, warnings = redact_secrets(text, "multi.py")
    assert any("line 4" in w for w in warnings)


# ---------------------------------------------------------------------------
# Redaction does not modify surrounding text
# ---------------------------------------------------------------------------

def test_surrounding_text_intact_aws():
    key = "AKIA" + "IOSFODNN7EXAMPLE123"
    text = f"PREFIX_{key}_SUFFIX"
    result, _ = redact_secrets(text, "f.py")
    assert result.startswith("PREFIX_")
    assert result.endswith("_SUFFIX")

def test_no_secrets_returns_original():
    text = "just some normal text with no secrets"
    result, warnings = redact_secrets(text, "f.py")
    assert result == text
    assert warnings == []

def test_empty_string():
    result, warnings = redact_secrets("", "f.py")
    assert result == ""
    assert warnings == []
