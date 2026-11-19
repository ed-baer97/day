"""Владельцы заправок в памяти процесса.

Владелец может вести одну или несколько заправок.
"""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

from app.config import get_settings
from app.domain.entities import StationOwner
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.services.account_helpers import clean_owner_username, require_owner_password
from app.services.memory_state import persist, register_store
from app.services.passwords import hash_password, verify_password

_lock = threading.Lock()
_owners: list[StationOwner] = []


def reset_station_accounts() -> None:
    global _owners
    with _lock:
        _owners = []


def _sync(account: StationOwner) -> None:
    if not account.station_ids:
        account.station_ids = [account.station_id]
    account.station_id = account.station_ids[0]


def create_owner(station_id: UUID, username: str, password: str) -> StationOwner:
    return grant_owner(station_id, username, password)


def grant_owner(station_id: UUID, username: str, password: str) -> StationOwner:
    """Создаёт владельца или добавляет ему ещё одну заправку."""
    cleaned = clean_owner_username(username, get_settings().admin_username)
    with _lock:
        existing = next((row for row in _owners if row.username == cleaned), None)
        if existing is not None:
            if station_id not in existing.stations():
                existing.station_ids = [*existing.stations(), station_id]
            _sync(existing)
            owner = existing
        else:
            require_owner_password(password)
            owner = StationOwner(
                id=uuid4(),
                station_id=station_id,
                username=cleaned,
                password_hash=hash_password(password),
                kind="owner",
                station_ids=[station_id],
            )
            _owners.append(owner)
    persist()
    return owner


def list_owners(station_id: UUID) -> list[StationOwner]:
    with _lock:
        return [owner for owner in _owners if owner.kind == "owner" and station_id in owner.stations()]


def has_owner(username: str) -> bool:
    cleaned = username.strip().lower()
    if not cleaned:
        return False
    with _lock:
        return any(row.username == cleaned and row.kind == "owner" for row in _owners)


def list_all_owners() -> list[StationOwner]:
    with _lock:
        owners = [owner for owner in _owners if owner.kind == "owner"]
        owners.sort(key=lambda row: row.username)
        return [
            StationOwner(
                id=owner.id,
                station_id=owner.station_id,
                username=owner.username,
                password_hash=owner.password_hash,
                kind=owner.kind,
                station_ids=owner.stations(),
            )
            for owner in owners
        ]


def create_owner_account(username: str, password: str, station_ids: list[UUID]) -> StationOwner:
    cleaned = clean_owner_username(
        username,
        get_settings().admin_username,
        empty_detail="укажите логин владельца",
    )
    require_owner_password(password)
    unique_ids = list(dict.fromkeys(station_ids))
    if not unique_ids:
        raise ValidationError("укажите хотя бы одну АГЗС")
    with _lock:
        if any(row.username == cleaned for row in _owners):
            raise ConflictError("владелец с таким логином уже существует")
        owner = StationOwner(
            id=uuid4(),
            station_id=unique_ids[0],
            username=cleaned,
            password_hash=hash_password(password),
            kind="owner",
            station_ids=unique_ids,
        )
        _owners.append(owner)
    persist()
    return owner


def update_owner_account(
    username: str,
    *,
    station_ids: list[UUID] | None = None,
    password: str | None = None,
) -> StationOwner:
    cleaned = username.strip().lower()
    if not cleaned:
        raise NotFoundError("владелец не найден")
    with _lock:
        owner = next((row for row in _owners if row.username == cleaned and row.kind == "owner"), None)
        if owner is None:
            raise NotFoundError("владелец не найден")
        if station_ids is not None:
            unique_ids = list(dict.fromkeys(station_ids))
            if not unique_ids:
                raise ValidationError("оставьте хотя бы одну АГЗС или удалите владельца")
            owner.station_ids = unique_ids
            _sync(owner)
        if password is not None:
            require_owner_password(password)
            owner.password_hash = hash_password(password)
    persist()
    return owner


def detach_owner_station(station_id: UUID, username: str) -> None:
    cleaned = username.strip().lower()
    with _lock:
        owner = next(
            (
                row
                for row in _owners
                if row.username == cleaned and row.kind == "owner" and station_id in row.stations()
            ),
            None,
        )
        if owner is None:
            raise NotFoundError("владелец не привязан к этой АГЗС")
        remaining = [sid for sid in owner.stations() if sid != station_id]
        if not remaining:
            _owners[:] = [row for row in _owners if row.username != cleaned]
        else:
            owner.station_ids = remaining
            _sync(owner)
    persist()


def delete_owner_account(username: str) -> None:
    cleaned = username.strip().lower()
    with _lock:
        before = len(_owners)
        _owners[:] = [row for row in _owners if not (row.username == cleaned and row.kind == "owner")]
        if len(_owners) == before:
            raise NotFoundError("владелец не найден")
    persist()


def authenticate_owner(username: str, password: str) -> StationOwner | None:
    cleaned = username.strip().lower()
    if not cleaned:
        return None
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
        restored.append(
            StationOwner(
                id=UUID(str(row["id"])),
                station_id=station_ids[0],
                username=str(row["username"]),
                password_hash=str(row["password_hash"]),
                kind="owner",
                station_ids=station_ids,
            )
        )
    global _owners
    with _lock:
        _owners = restored


register_store("owners", snapshot, restore_snapshot)

__all__ = [
    "StationOwner",
    "authenticate_owner",
    "create_owner",
    "create_owner_account",
    "delete_owner_account",
    "detach_owner_station",
    "grant_owner",
    "has_owner",
    "list_all_owners",
    "list_owners",
    "reset_station_accounts",
    "restore_snapshot",
    "snapshot",
    "update_owner_account",
]
