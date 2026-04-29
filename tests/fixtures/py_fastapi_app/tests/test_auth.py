import hashlib
from app.auth import verify_token


def test_verify_valid_token():
    token = hashlib.sha256(b"secret").hexdigest()
    assert verify_token(token) is True


def test_verify_invalid_token():
    assert verify_token("bad-token") is False
