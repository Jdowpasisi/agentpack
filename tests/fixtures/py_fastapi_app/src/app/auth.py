import hashlib
from fastapi import APIRouter, HTTPException

router = APIRouter()

_USERS: dict[str, str] = {"alice": hashlib.sha256(b"secret").hexdigest()}


def verify_token(token: str) -> bool:
    return token in _USERS.values()


@router.post("/login")
def login(username: str, password: str) -> dict:
    hashed = hashlib.sha256(password.encode()).hexdigest()
    if _USERS.get(username) != hashed:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": hashed}


@router.post("/refresh")
def refresh_token(token: str) -> dict:
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"token": token}
