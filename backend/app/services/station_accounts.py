"""Владельцы заправок в памяти процесса.

Владелец может вести одну или несколько заправок.
"""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

from app.config import get_settings
from app.domain.entities import StationOwner
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
    "grant_owner",
    "list_owners",
    "reset_station_accounts",
    "restore_snapshot",
    "snapshot",
]
