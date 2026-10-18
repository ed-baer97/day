"""Сессия администратора: подпись токена и проверка входа."""

import base64
import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Header, HTTPException

from app.config import get_settings


def _same(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def issue_token(username: str, secret: str, ttl_seconds: int = 12 * 3600) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = f"{expires}:{username}".encode()
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    blob = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{blob}.{signature}"


def read_token(token: str, secret: str) -> str | None:
    blob, dot, signature = token.partition(".")
    if not blob or not dot or not signature:
        return None
    try:
        payload = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        expires_raw, username = payload.decode().split(":", 1)
        expires = int(expires_raw)
    except ValueError:
        return None
    if time.time() >= expires or not username:
        return None
    return username


def credentials_match(username: str, password: str) -> bool:
    settings = get_settings()
    return _same(username, settings.admin_username) and _same(password, settings.admin_password)


def require_admin(authorization: Annotated[str | None, Header()] = None) -> str:
    settings = get_settings()
    if settings.auth_disabled:
        return settings.admin_username
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Нужен вход")
    username = read_token(authorization.split(" ", 1)[1].strip(), settings.auth_secret)
    if username != settings.admin_username:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    return username
