"""Владельцы заправок и администраторы пульта в памяти процесса.

Владелец может вести несколько заправок. Администратор пульта создаётся
владельцем и входит в пульт одной заправки. На площадке Postgres эти логины
пока остаются прежней таблицей и отсюда не расширяются.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.services.passwords import hash_password, verify_password

_lock = threading.Lock()


@dataclass
class StationOwner:
    id: UUID
    station_id: UUID
    username: str
    password_hash: str
    kind: str = "owner"
    station_ids: list[UUID] = field(default_factory=list)

    def stations(self) -> list[UUID]:
        if self.station_ids:
            return list(self.station_ids)
        return [self.station_id]


_owners: list[StationOwner] = []


def reset_station_accounts() -> None:
    global _owners
    with _lock:
        _owners = []


def _commit() -> None:
    from app.services.memory_state import persist

    persist()


def _cleaned(username: str) -> str:
    cleaned = username.strip().lower()
    if not cleaned:
        raise HTTPException(status_code=422, detail="укажите логин")
    admin_name = get_settings().admin_username.strip().lower()
    if cleaned == admin_name:
        raise HTTPException(status_code=409, detail="этот логин занят администратором платформы")
    return cleaned


def _sync(account: StationOwner) -> None:
    if not account.station_ids:
        account.station_ids = [account.station_id]
    account.station_id = account.station_ids[0]


def create_owner(station_id: UUID, username: str, password: str) -> StationOwner:
    return grant_owner(station_id, username, password)


def grant_owner(station_id: UUID, username: str, password: str) -> StationOwner:
    """Создаёт владельца или добавляет ему ещё одну заправку."""

    cleaned = _cleaned(username)
    with _lock:
        existing = next((row for row in _owners if row.username == cleaned), None)
        if existing is not None:
            if existing.kind != "owner":
                raise HTTPException(status_code=409, detail="этот логин принадлежит администратору пульта")
            if station_id not in existing.stations():
                existing.station_ids = [*existing.stations(), station_id]
            _sync(existing)
            owner = existing
        else:
            if len(password) < 6:
                raise HTTPException(status_code=422, detail="пароль владельца не короче 6 символов")
            owner = StationOwner(
                id=uuid4(),
                station_id=station_id,
                username=cleaned,
                password_hash=hash_password(password),
                kind="owner",
                station_ids=[station_id],
            )
            _owners.append(owner)
    _commit()
    return owner


def create_console_admin(station_id: UUID, username: str, password: str) -> StationOwner:
    cleaned = _cleaned(username)
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="пароль администратора пульта не короче 6 символов")
    with _lock:
        if any(row.username == cleaned for row in _owners):
            raise HTTPException(status_code=409, detail="логин уже занят")
        admin = StationOwner(
            id=uuid4(),
            station_id=station_id,
            username=cleaned,
            password_hash=hash_password(password),
            kind="console",
            station_ids=[station_id],
        )
        _owners.append(admin)
    _commit()
    return admin


def list_owners(station_id: UUID) -> list[StationOwner]:
    with _lock:
        return [owner for owner in _owners if owner.kind == "owner" and station_id in owner.stations()]


def list_console_admins(station_id: UUID) -> list[StationOwner]:
    with _lock:
        return [row for row in _owners if row.kind == "console" and station_id in row.stations()]


def authenticate_owner(username: str, password: str) -> StationOwner | None:
    cleaned = username.strip().lower()
    with _lock:
        owner = next((row for row in _owners if row.username == cleaned), None)
        if owner is None:
            return None
        password_hash = owner.password_hash
        found = owner
    if not verify_password(password, password_hash):
        return None
    return found


def snapshot() -> list[dict]:
    with _lock:
        return [
            {
                "id": str(owner.id),
                "station_id": str(owner.station_id),
                "username": owner.username,
                "password_hash": owner.password_hash,
                "kind": owner.kind,
                "station_ids": [str(item) for item in owner.stations()],
            }
            for owner in _owners
        ]


def restore_snapshot(rows: object) -> None:
    if not isinstance(rows, list):
        return
    restored: list[StationOwner] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_ids = row.get("station_ids")
        if isinstance(raw_ids, list) and raw_ids:
            station_ids = [UUID(str(item)) for item in raw_ids]
        else:
            station_ids = [UUID(str(row["station_id"]))]
        kind = str(row.get("kind") or "owner")
        if kind not in {"owner", "console"}:
            kind = "owner"
        restored.append(
            StationOwner(
                id=UUID(str(row["id"])),
                station_id=station_ids[0],
                username=str(row["username"]),
                password_hash=str(row["password_hash"]),
                kind=kind,
                station_ids=station_ids,
            )
        )
    global _owners
    with _lock:
        _owners = restored
