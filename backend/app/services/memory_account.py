"""Адаптер учёта в памяти процесса.

Функции совпадают по именам с postgres_account, чтобы порт выбирал адаптер в одном месте.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.ingest import IngestAck
from app.services.catalog import (
    create_station,
    create_truck,
    delete_station,
    delete_truck,
    get_station,
    get_truck,
    list_stations,
    list_trucks,
    record_truck_position,
    update_station,
    update_truck,
)
from app.services.device_ingest import (
    accept_dispense,
    accept_dispenses_batch,
    accept_level,
    accept_levels_batch,
    accept_receipt,
    bind_calibration,
    bind_dispense,
    bind_level,
    bind_receipt,
    delete_tank_device,
    get_tank_device,
    has_calibration,
    list_station_tanks_out,
    list_tank_devices,
    register_tank,
    set_calibration,
    tank_by_token,
    tank_remainder,
    tank_state,
    update_tank_device,
)
from app.services.station_accounts import (
    authenticate_owner as authenticate_station_user,
    grant_owner as create_station_user,
    list_owners as list_station_users,
)


def list_active_stations_with_tanks():
    stations = [station for station in list_stations() if station.is_active]
    return [(station, list_station_tanks_out(station.id)) for station in stations]


def list_level_readings(
    station_id: UUID,
    tank_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> list:
    """В памяти журнал замеров не хранится: витрина читает текущий остаток."""
    del station_id, tank_id, since, limit, newest_first
    return []


__all__ = [
    "accept_dispense",
    "accept_dispenses_batch",
    "accept_level",
    "accept_levels_batch",
    "accept_receipt",
    "authenticate_station_user",
    "bind_calibration",
    "bind_dispense",
    "bind_level",
    "bind_receipt",
    "create_station",
    "create_station_user",
    "create_truck",
    "delete_station",
    "delete_tank_device",
    "delete_truck",
    "get_station",
    "get_tank_device",
    "get_truck",
    "has_calibration",
    "list_active_stations_with_tanks",
    "list_level_readings",
    "list_station_tanks_out",
    "list_station_users",
    "list_stations",
    "list_tank_devices",
    "list_trucks",
    "record_truck_position",
    "register_tank",
    "set_calibration",
    "tank_by_token",
    "tank_remainder",
    "tank_state",
    "update_station",
    "update_tank_device",
    "update_truck",
    "IngestAck",
]
