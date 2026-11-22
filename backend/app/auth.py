"""Сессия учёта: admin или пользователь станции, защита от перебора."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException

from app.config import get_settings
from app.domain.access import (
    ROLE_ADMIN,
    ROLE_CASHIER,
    ROLES,
    is_admin_role,
    is_cashier_role,
    is_owner_role,
    may_list_cashiers,
    may_manage_cashiers,
    may_manage_catalog,
    may_operate_shift,
    may_read_station,
    may_read_station_cashiers,
)

_lock = threading.Lock()
_revoked_tokens: set[str] = set()
_MAX_REVOKED = 4096

_LOGIN_WINDOW_SECONDS = 60.0
_MAX_FAILED_ATTEMPTS = 5
_failed_logins: dict[str, list[float]] = defaultdict(list)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    station_id: UUID | None = None
    station_ids: tuple[UUID, ...] = ()

    @property
    def is_admin(self) -> bool:
        return is_admin_role(self.role)

    @property
    def is_owner(self) -> bool:
        return is_owner_role(self.role)

    @property
    def is_cashier(self) -> bool:
        return is_cashier_role(self.role)

    def stations(self) -> tuple[UUID, ...]:
        if self.station_ids:
            return self.station_ids
        if self.station_id is not None:
            return (self.station_id,)
        return ()


def reset_auth_state() -> None:
    with _lock:
        _revoked_tokens.clear()
        _failed_logins.clear()


def check_login_rate_limit(client_key: str) -> None:
    now = time.monotonic()
    with _lock:
        attempts = [t for t in _failed_logins.get(client_key, []) if now - t < _LOGIN_WINDOW_SECONDS]
        if attempts:
            _failed_logins[client_key] = attempts
        else:
            _failed_logins.pop(client_key, None)
        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Слишком много неудачных попыток входа. Подождите минуту.",
            )


def record_login_failure(client_key: str) -> None:
    now = time.monotonic()
    with _lock:
        attempts = [t for t in _failed_logins.get(client_key, []) if now - t < _LOGIN_WINDOW_SECONDS]
        attempts.append(now)
        if len(_failed_logins) > 2048:
            _failed_logins.clear()
        _failed_logins[client_key] = attempts


def clear_login_failures(client_key: str) -> None:
    with _lock:
        _failed_logins.pop(client_key, None)


def revoke_token(token: str) -> None:
    with _lock:
        if len(_revoked_tokens) >= _MAX_REVOKED:
            _revoked_tokens.clear()
        _revoked_tokens.add(token)


def _same(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def issue_token(
    username: str,
    secret: str,
    *,
    role: str = ROLE_ADMIN,
    station_id: UUID | None = None,
    station_ids: list[UUID] | tuple[UUID, ...] | None = None,
    ttl_seconds: int = 12 * 3600,
) -> str:
    expires = int(time.time()) + ttl_seconds
    nonce = secrets.token_hex(8)
    ids = list(station_ids) if station_ids is not None else ([] if station_id is None else [station_id])
    station = ",".join(str(item) for item in ids)
    payload = f"{expires}:{nonce}:{username}:{role}:{station}".encode()
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    blob = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{blob}.{signature}"


def _decode_verified_payload(token: str, secret: str) -> bytes | None:
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
    return payload


def _parse_token_fields(payload: bytes) -> tuple[int, str, str, str] | None:
    try:
        parts = payload.decode().split(":")
        if len(parts) == 2:
            # Самый старый формат: expires:username
            expires_raw, username = parts
            role, station_raw = ROLE_ADMIN, ""
        elif len(parts) == 3:
            # expires:nonce:username
            expires_raw, _nonce, username = parts
            role, station_raw = ROLE_ADMIN, ""
        elif len(parts) >= 5:
            # expires:nonce:username:role:station_id
            expires_raw = parts[0]
            username = parts[2]
            role = parts[3] or ROLE_ADMIN
            station_raw = parts[4]
        else:
            return None
        return int(expires_raw), username, role, station_raw
    except ValueError:
        return None


def read_principal(token: str, secret: str) -> Principal | None:
    with _lock:
        if token in _revoked_tokens:
            return None
    payload = _decode_verified_payload(token, secret)
    if payload is None:
        return None
    parsed = _parse_token_fields(payload)
    if parsed is None:
        return None
    expires, username, role, station_raw = parsed
    if time.time() >= expires or not username:
        return None
    station_ids: list[UUID] = []
    if station_raw:
        try:
            station_ids = [UUID(part) for part in station_raw.split(",") if part]
        except ValueError:
            return None
    if role not in ROLES:
        return None
    if role != ROLE_ADMIN and not station_ids:
        return None
    if role == ROLE_CASHIER and len(station_ids) != 1:
        return None
    station_id = station_ids[0] if len(station_ids) == 1 else None
    return Principal(
        username=username,
        role=role,
        station_id=station_id,
        station_ids=tuple(station_ids),
    )


def read_token(token: str, secret: str) -> str | None:
    principal = read_principal(token, secret)
    return None if principal is None else principal.username


def credentials_match(username: str, password: str) -> bool:
    settings = get_settings()
    return _same(username, settings.admin_username) and _same(password, settings.admin_password)


def is_admin_authorization(authorization: str | None) -> bool:
    settings = get_settings()
    if settings.auth_disabled:
        return True
    principal = current_principal(authorization)
    return principal is not None and principal.is_admin


def has_valid_admin_token(authorization: str | None) -> bool:
    """Проверяет реальный Bearer-токен администратора, не учитывая AUTH_DISABLED."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return False
    principal = read_principal(token, get_settings().auth_secret)
    return principal is not None and principal.is_admin


def current_principal(authorization: str | None) -> Principal | None:
    settings = get_settings()
    if settings.auth_disabled:
        return Principal(username=settings.admin_username, role=ROLE_ADMIN)
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return read_principal(authorization.split(" ", 1)[1].strip(), settings.auth_secret)


def require_admin(authorization: Annotated[str | None, Header()] = None) -> str:
    principal = require_principal(authorization)
    if not may_manage_catalog(principal.role):
        raise HTTPException(status_code=403, detail="Нужны права администратора")
    return principal.username


def require_principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
    settings = get_settings()
    if settings.auth_disabled:
        return Principal(username=settings.admin_username, role=ROLE_ADMIN)
    principal = current_principal(authorization)
    if principal is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    return principal


def require_station_access(station_id: UUID, principal: Principal) -> None:
    if may_read_station(principal.role, principal.stations(), station_id):
        return
    raise HTTPException(status_code=403, detail="чужая заправка")


def require_cashiers_reader(principal: Principal) -> None:
    if may_list_cashiers(principal.role):
        return
    raise HTTPException(status_code=403, detail="доступ только для владельца или администратора")


def require_station_owner(station_id: UUID, principal: Principal) -> None:
    if may_manage_cashiers(principal.role, principal.stations(), station_id):
        return
    require_station_access(station_id, principal)
    raise HTTPException(status_code=403, detail="это делает владелец заправки")


def require_station_cashier(station_id: UUID, principal: Principal) -> None:
    if may_operate_shift(principal.role, principal.stations(), station_id):
        return
    require_station_access(station_id, principal)
    raise HTTPException(status_code=403, detail="это делает кассир заправки")


def require_station_manager_or_admin(station_id: UUID, principal: Principal) -> None:
    if may_read_station_cashiers(principal.role, principal.stations(), station_id):
        return
    require_station_access(station_id, principal)
    raise HTTPException(status_code=403, detail="доступ только для администратора или владельца")
