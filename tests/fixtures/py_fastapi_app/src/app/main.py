from fastapi import FastAPI
from app.auth import router as auth_router
from app.users import router as users_router

app = FastAPI(title="Demo App")
app.include_router(auth_router, prefix="/auth")
app.include_router(users_router, prefix="/users")
