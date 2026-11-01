"""Вход и завершение сессии в системе учёта."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.auth import (
    check_login_rate_limit,
    clear_login_failures,
    credentials_match,
    issue_token,
    record_login_failure,
    require_admin,
    require_principal,
    revoke_token,
)
from app.config import get_settings
from app.schemas.auth import LoginIn, SessionOut
from app.services.account_mode import use_postgres

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request) -> SessionOut:
    client_host = request.client.host if request.client else "local"
    key = f"{client_host}:{body.username.strip().lower()}"
    check_login_rate_limit(key)
    settings = get_settings()
    if credentials_match(body.username, body.password):
        clear_login_failures(key)
        return SessionOut(
            token=issue_token(body.username, settings.auth_secret, role="admin"),
            username=settings.admin_username,
            role="admin",
            station_id=None,
        )
    if use_postgres():
        from app.services import postgres_account

        user = postgres_account.authenticate_station_user(body.username, body.password)
        if user is not None:
            clear_login_failures(key)
            return SessionOut(
                token=issue_token(
                    user.username,
                    settings.auth_secret,
                    role="station",
                    station_id=user.station_id,
                ),
                username=user.username,
                role="station",
                station_id=user.station_id,
            )
    record_login_failure(key)
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")


@router.post("/logout")
def logout(
    authorization: Annotated[str | None, Header()] = None,
    _user=Depends(require_principal),
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        revoke_token(authorization.split(" ", 1)[1].strip())
    return {"status": "ok"}


@router.get("/me")
def me(principal=Depends(require_principal)) -> dict:
    return {
        "username": principal.username,
        "role": principal.role,
        "station_id": None if principal.station_id is None else str(principal.station_id),
    }
