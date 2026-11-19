"""Адаптер учёта в памяти процесса.

Функции совпадают по именам с postgres_account, чтобы порт выбирал адаптер в одном месте.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.domain.entities import TankDevice
from app.schemas.ingest import IngestAck
from app.services.catalog import (
    create_station,
    create_truck,
    delete_station as _delete_station_card,
    delete_truck,
    get_station,
    get_truck,
    list_stations,
    list_trucks,
    update_station,
    update_truck,
)
from app.services.device_ingest import (
    accept_dispense,
    accept_dispenses_batch,
    accept_level,
    accept_levels_batch,
    accept_receipt,
    delete_station_devices,
    delete_tank_device,
    get_tank_device,
    has_calibration,
    list_dispense_records,
    list_station_tanks_out,
    list_tank_devices,
    register_tank as _register_tank_device,
    rotate_tank_token as _rotate_tank_token,
    set_calibration,
    tank_by_token,
    tank_remainder,
    tank_state,
    tank_state_or_none,
    update_tank_device,
)
from app.services.station_accounts import (
    authenticate_owner as authenticate_station_user,
    create_owner_account as _create_owner_account,
    delete_owner_account as delete_owner_account,
    detach_owner_station as _detach_owner_station,
    grant_owner as _grant_owner,
    has_owner,
    list_all_owners,
    list_owners as _list_owners,
    update_owner_account as _update_owner_account,
)


def delete_station(station_id: UUID) -> list[UUID]:
    _delete_station_card(station_id)
    return delete_station_devices(station_id)


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    get_station(station_id)
    return _register_tank_device(station_id, code, capacity_liters)


def list_station_users(station_id: UUID):
    get_station(station_id)
    return _list_owners(station_id)


def create_station_user(station_id: UUID, username: str, password: str):
    get_station(station_id)
    return _grant_owner(station_id, username, password)


def rotate_tank_token(station_id: UUID, tank_id: UUID) -> TankDevice:
    get_station(station_id)
    return _rotate_tank_token(station_id, tank_id)


def create_owner_account(username: str, password: str, station_ids: list[UUID]):
    for sid in station_ids:
        get_station(sid)
    return _create_owner_account(username, password, station_ids)


def update_owner_account(
    username: str,
    *,
    station_ids: list[UUID] | None = None,
    password: str | None = None,
):
    if station_ids is not None:
        for sid in station_ids:
            get_station(sid)
    return _update_owner_account(username, station_ids=station_ids, password=password)


def detach_station_user(station_id: UUID, username: str) -> None:
    get_station(station_id)
    _detach_owner_station(station_id, username)


def list_active_stations_with_tanks():
    stations = [station for station in list_stations() if station.is_active]
    return [(station, list_station_tanks_out(station.id)) for station in stations]


def list_all_stations_with_overview():
    result = []
    for station in list_stations():
        devices = list_tank_devices(station.id)
        pairs = [(device, tank_state_or_none(station.id, device.tank_id)) for device in devices]
        result.append((station, pairs))
    return result


def list_level_readings(
    station_id: UUID,
    tank_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> list:
    """В памяти журнал замеров не хранится: витрина читает текущий остаток."""
    get_tank_device(station_id, tank_id)
    del since, limit, newest_first
    return []


__all__ = [
    "IngestAck",
    "accept_dispense",
    "accept_dispenses_batch",
    "accept_level",
    "accept_levels_batch",
    "accept_receipt",
    "authenticate_station_user",
    "create_owner_account",
    "create_station",
    "create_station_user",
    "create_truck",
    "delete_owner_account",
    "delete_station",
    "delete_tank_device",
    "delete_truck",
    "detach_station_user",
    "get_station",
    "get_tank_device",
    "get_truck",
    "has_calibration",
    "has_owner",
    "list_active_stations_with_tanks",
    "list_all_owners",
    "list_all_stations_with_overview",
    "list_dispense_records",
    "list_level_readings",
    "list_station_tanks_out",
    "list_station_users",
    "list_stations",
    "list_tank_devices",
    "list_trucks",
    "register_tank",
    "rotate_tank_token",
    "set_calibration",
    "tank_by_token",
    "tank_remainder",
    "tank_state",
    "update_owner_account",
    "update_station",
    "update_tank_device",
    "update_truck",
]
