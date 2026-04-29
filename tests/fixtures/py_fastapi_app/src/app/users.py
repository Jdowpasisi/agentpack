from fastapi import APIRouter, HTTPException
from app.auth import verify_token

router = APIRouter()

_DB: dict[int, dict] = {1: {"id": 1, "name": "Alice", "email": "alice@example.com"}}
_NEXT_ID = 2


@router.get("/{user_id}")
def get_user(user_id: int, token: str) -> dict:
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = _DB.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/")
def create_user(name: str, email: str, token: str) -> dict:
    global _NEXT_ID
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = {"id": _NEXT_ID, "name": name, "email": email}
    _DB[_NEXT_ID] = user
    _NEXT_ID += 1
    return user
