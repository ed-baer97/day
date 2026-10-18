"""Вход в учёт."""

from fastapi import APIRouter, HTTPException

from app.auth import credentials_match, issue_token
from app.config import get_settings
from app.schemas.auth import LoginIn, SessionOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn) -> SessionOut:
    if not credentials_match(body.username, body.password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    settings = get_settings()
    return SessionOut(token=issue_token(body.username, settings.auth_secret), username=settings.admin_username)
