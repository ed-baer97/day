"""Адаптер учёта в памяти процесса.

Функции совпадают по именам с postgres_account, чтобы порт выбирал адаптер в одном месте.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.domain.entities import TankDevice
from app.schemas.ingest import IngestAck
from app.services.batch_book import (
    add_batch_event,
    by_code as get_batch_by_code,
    by_id as get_batch_by_id,
    create_batch,
    list_batches,
    update_batch_status,
)
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
    list_receipt_volume,
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
from app.services.shift_book import (
    close_shift as _close_shift,
    delete_station_shifts as _delete_station_shifts,
    get_open_shift as _get_open_shift,
    get_shift as _get_shift,
    list_shifts as _list_shifts,
    open_shift as _open_shift,
)
from app.services.station_accounts import (
    authenticate_owner as authenticate_station_user,
    create_owner_account as _create_owner_account,
    create_station_cashier as _create_station_cashier,
    delete_owner_account as delete_owner_account,
    delete_station_cashier as _delete_station_cashier,
    detach_owner_station as _detach_owner_station,
    grant_owner as _grant_owner,
    has_owner,
    list_all_owners,
    list_cashiers_for_stations,
    list_owners as _list_owners,
    list_station_cashiers as _list_station_cashiers,
    remove_station_from_accounts as _remove_station_from_accounts,
    update_owner_account as _update_owner_account,
    update_station_cashier as _update_station_cashier,
)


def delete_station(station_id: UUID) -> list[UUID]:
    _delete_station_card(station_id)
    _remove_station_from_accounts(station_id)
    _delete_station_shifts(station_id)
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


def list_station_cashiers(station_id: UUID):
    get_station(station_id)
    return _list_station_cashiers(station_id)


def create_station_cashier(station_id: UUID, username: str, password: str):
    get_station(station_id)
    return _create_station_cashier(station_id, username, password)


def update_station_cashier(
    station_id: UUID,
    username: str,
    *,
    password: str | None = None,
    new_station_id: UUID | None = None,
):
    get_station(station_id)
    if new_station_id is not None:
        get_station(new_station_id)
    return _update_station_cashier(
        station_id,
        username,
        password=password,
        new_station_id=new_station_id,
    )


def delete_station_cashier(station_id: UUID, username: str) -> None:
    get_station(station_id)
    _delete_station_cashier(station_id, username)


def list_shifts(station_id: UUID, *, limit: int = 50):
    get_station(station_id)
    return _list_shifts(station_id, limit=limit)


def get_shift(station_id: UUID, shift_id: UUID):
    get_station(station_id)
    return _get_shift(station_id, shift_id)


def get_open_shift(station_id: UUID):
    get_station(station_id)
    return _get_open_shift(station_id)


def open_shift(station_id: UUID, **kwargs):
    get_station(station_id)
    return _open_shift(station_id, **kwargs)


def close_shift(station_id: UUID, shift_id: UUID, **kwargs):
    get_station(station_id)
    return _close_shift(station_id, shift_id, **kwargs)


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
    "add_batch_event",
    "authenticate_station_user",
    "close_shift",
    "create_batch",
    "create_owner_account",
    "create_station",
    "create_station_cashier",
    "create_station_user",
    "create_truck",
    "delete_owner_account",
    "delete_station",
    "delete_station_cashier",
    "delete_tank_device",
    "delete_truck",
    "detach_station_user",
    "get_batch_by_code",
    "get_batch_by_id",
    "get_open_shift",
    "get_shift",
    "get_station",
    "get_tank_device",
    "get_truck",
    "has_calibration",
    "has_owner",
    "list_active_stations_with_tanks",
    "list_all_owners",
    "list_all_stations_with_overview",
    "list_batches",
    "list_cashiers_for_stations",
    "list_dispense_records",
    "list_level_readings",
    "list_receipt_volume",
    "list_shifts",
    "list_station_cashiers",
    "list_station_tanks_out",
    "list_station_users",
    "list_stations",
    "list_tank_devices",
    "list_trucks",
    "open_shift",
    "register_tank",
    "rotate_tank_token",
    "set_calibration",
    "tank_by_token",
    "tank_remainder",
    "tank_state",
    "update_batch_status",
    "update_owner_account",
    "update_station",
    "update_station_cashier",
    "update_tank_device",
    "update_truck",
]
