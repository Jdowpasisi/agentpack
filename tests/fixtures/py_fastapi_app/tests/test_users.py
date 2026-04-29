import hashlib
from app.auth import verify_token


def test_users_module_imports():
    from app.users import _DB
    assert 1 in _DB
